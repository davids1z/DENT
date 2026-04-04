#!/usr/bin/env python3
"""Export SPAI PyTorch model to ONNX (encoder + aggregator).

Must be run in an environment with timm==0.4.12 (incompatible with DENT's timm>=1.0).
Typically run on a vast.ai GPU instance.

Usage:
  pip install timm==0.4.12 torch einops yacs onnx onnxscript
  git clone https://github.com/mever-team/spai.git /tmp/spai
  cd /tmp/spai
  # Download weights: gdown 1... -O weights/spai.pth (or manual download)
  python3 /path/to/export_spai_onnx.py --weights weights/spai.pth --output /tmp/spai_onnx/

Produces: encoder.onnx + aggregator.onnx
Upload these to S3 or copy to production server at models/spai/
"""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Export SPAI to ONNX")
    parser.add_argument("--weights", required=True, help="Path to spai.pth")
    parser.add_argument("--output", default="./spai_onnx", help="Output directory")
    parser.add_argument("--spai-repo", default="/tmp/spai", help="Path to cloned SPAI repo")
    args = parser.parse_args()

    # Add SPAI repo to path
    sys.path.insert(0, args.spai_repo)

    import torch

    os.makedirs(args.output, exist_ok=True)

    print("Loading SPAI model...")
    from spai.models.sid import SID
    from spai.config import get_cfg_defaults

    cfg = get_cfg_defaults()
    cfg.merge_from_file(os.path.join(args.spai_repo, "configs", "spai.yaml"))
    cfg.freeze()

    model = SID(cfg)
    state_dict = torch.load(args.weights, map_location="cpu")
    if "model" in state_dict:
        state_dict = state_dict["model"]
    model.load_state_dict(state_dict, strict=False)
    model.eval()
    print("Model loaded")

    # Export encoder (without FFT preprocessing baked in)
    print("Exporting encoder ONNX (3 inputs: x, x_low, x_high)...")
    model.export_onnx_without_fft(
        os.path.join(args.output, "encoder.onnx"),
    )
    print(f"  Saved: {args.output}/encoder.onnx")

    # Export aggregator
    print("Exporting aggregator ONNX...")
    model.export_onnx_patch_aggregator(
        os.path.join(args.output, "aggregator.onnx"),
    )
    print(f"  Saved: {args.output}/aggregator.onnx")

    # Verify
    import onnx
    enc = onnx.load(os.path.join(args.output, "encoder.onnx"))
    agg = onnx.load(os.path.join(args.output, "aggregator.onnx"))
    print(f"\nEncoder inputs: {[i.name for i in enc.graph.input]}")
    print(f"Encoder output shape: {[o.name for o in enc.graph.output]}")
    print(f"Aggregator inputs: {[i.name for i in agg.graph.input]}")
    print(f"Aggregator output shape: {[o.name for o in agg.graph.output]}")
    print(f"\nDone! Copy {args.output}/ to production server at models/spai/")


if __name__ == "__main__":
    main()
