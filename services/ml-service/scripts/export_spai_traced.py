#!/usr/bin/env python3
"""Export SPAI model to TorchScript traced format.

Unlike ONNX export (which has torch/onnxscript version hell), TorchScript
traced models work with any PyTorch >= 1.8 at inference time.

Must be run with timm==0.4.12 (SPAI requirement).

Usage on vast.ai:
  pip install timm==0.4.12 einops yacs scipy seaborn matplotlib \
    opencv-python-headless neptune albumentations==1.4.14 \
    filetype lmdb tensorboard clip
  apt-get install -y libgl1-mesa-glx libglib2.0-0
  git clone https://github.com/mever-team/spai.git /tmp/spai
  # Download weights
  gdown 1vvXmZqs6TVJdj8iF1oJ4L_fcgdQrp_YI -O /tmp/spai/weights/spai.pth
  # Export
  python3 export_spai_traced.py --spai-repo /tmp/spai --output /tmp/spai_traced/

Produces: encoder.pt + aggregator.pt (TorchScript files)
"""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Export SPAI to TorchScript")
    parser.add_argument("--spai-repo", default="/tmp/spai", help="Path to SPAI repo")
    parser.add_argument("--output", default="/tmp/spai_traced", help="Output directory")
    args = parser.parse_args()

    sys.path.insert(0, args.spai_repo)
    os.makedirs(args.output, exist_ok=True)

    import torch
    print(f"PyTorch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")

    # Load SPAI config + model
    from spai.config import _C
    from spai.models.sid import PatchBasedMFViT

    cfg = _C.clone()
    cfg.merge_from_file(os.path.join(args.spai_repo, "configs", "spai.yaml"))
    cfg.freeze()

    weights_path = os.path.join(args.spai_repo, "weights", "spai.pth")
    print(f"Loading weights from {weights_path}...")

    # Build the full model
    from spai.models.build import build_cls_model
    model = build_cls_model(cfg)

    # Load pretrained weights
    sd = torch.load(weights_path, map_location="cpu")
    if "model" in sd:
        sd = sd["model"]
    model.load_state_dict(sd, strict=False)
    model.eval()
    print(f"Model loaded: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params")

    # The model has two components:
    # 1. mfvit (MFViT encoder) — takes 3 images (orig, low, high) each 224x224
    # 2. patches_attention + classification_head (aggregator)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)

    # ── Export Encoder ──────────────────────────────────────────────
    # The encoder (mfvit) processes one patch at a time
    # Input: 3 tensors of (1, 3, 224, 224) — original, low-freq, high-freq
    # Output: (1, feature_dim) — e.g., (1, 1096)
    print("\nTracing encoder...")
    mfvit = model.mfvit
    mfvit.eval()

    # Create dummy inputs
    dummy_x = torch.randn(1, 3, 224, 224, device=device)
    dummy_low = torch.randn(1, 3, 224, 224, device=device)
    dummy_high = torch.randn(1, 3, 224, 224, device=device)

    # Try to trace the encoder
    # MFViT.forward() takes (x, x_low, x_high) and returns features
    try:
        traced_encoder = torch.jit.trace(mfvit, (dummy_x, dummy_low, dummy_high))
        encoder_path = os.path.join(args.output, "encoder.pt")
        traced_encoder.save(encoder_path)
        print(f"Encoder saved: {encoder_path} ({os.path.getsize(encoder_path)/1e6:.1f}MB)")

        # Verify
        with torch.no_grad():
            orig_out = mfvit(dummy_x, dummy_low, dummy_high)
            traced_out = traced_encoder(dummy_x, dummy_low, dummy_high)
            diff = (orig_out - traced_out).abs().max().item()
            print(f"Encoder verification: max diff = {diff:.2e} (should be ~0)")
            print(f"Encoder output shape: {orig_out.shape}")
    except Exception as e:
        print(f"Encoder tracing failed: {e}")
        print("Trying torch.jit.script instead...")
        try:
            scripted_encoder = torch.jit.script(mfvit)
            encoder_path = os.path.join(args.output, "encoder.pt")
            scripted_encoder.save(encoder_path)
            print(f"Encoder (scripted) saved: {encoder_path}")
        except Exception as e2:
            print(f"Encoder scripting also failed: {e2}")
            print("Saving raw state_dict instead...")
            torch.save(mfvit.state_dict(), os.path.join(args.output, "encoder_state_dict.pt"))
            print("Saved encoder state_dict (will need model class at inference)")

    # ── Export Aggregator ───────────────────────────────────────────
    # The aggregator takes (1, num_patches, feature_dim) and outputs (1, 1)
    print("\nTracing aggregator...")

    # Build a wrapper that does patches_attention + classification_head
    class Aggregator(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.patches_attention = model.patches_attention
            self.norm = model.norm if hasattr(model, 'norm') else None
            self.classification_head = model.classification_head

        def forward(self, x):
            # x: (B, L, D) where L = num_patches, D = feature_dim
            out = self.patches_attention(x)  # (B, D)
            if self.norm is not None:
                out = self.norm(out)
            out = self.classification_head(out)  # (B, 1)
            return out

    aggregator = Aggregator(model).to(device)
    aggregator.eval()

    # Get feature dim from encoder output
    with torch.no_grad():
        enc_out = mfvit(dummy_x, dummy_low, dummy_high)
        feat_dim = enc_out.shape[-1]
        print(f"Feature dim: {feat_dim}")

    dummy_patches = torch.randn(1, 4, feat_dim, device=device)  # 4 patches

    try:
        traced_aggregator = torch.jit.trace(aggregator, dummy_patches)
        aggregator_path = os.path.join(args.output, "aggregator.pt")
        traced_aggregator.save(aggregator_path)
        print(f"Aggregator saved: {aggregator_path} ({os.path.getsize(aggregator_path)/1e6:.1f}MB)")

        # Verify
        with torch.no_grad():
            orig_out = aggregator(dummy_patches)
            traced_out = traced_aggregator(dummy_patches)
            diff = (orig_out - traced_out).abs().max().item()
            print(f"Aggregator verification: max diff = {diff:.2e} (should be ~0)")
            print(f"Aggregator output shape: {orig_out.shape}")
    except Exception as e:
        print(f"Aggregator tracing failed: {e}")
        torch.save(aggregator.state_dict(), os.path.join(args.output, "aggregator_state_dict.pt"))
        print("Saved aggregator state_dict")

    print(f"\nDone! Files in {args.output}/:")
    for f in sorted(os.listdir(args.output)):
        p = os.path.join(args.output, f)
        print(f"  {f}: {os.path.getsize(p)/1e6:.1f}MB")


if __name__ == "__main__":
    main()
