"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

const MAX_IMAGES = 8;

interface GpsCoordinates {
  latitude: number;
  longitude: number;
  accuracy: number;
}

interface DeviceMeta {
  userAgent: string;
  cameraLabel: string;
  screenWidth: number;
  screenHeight: number;
  captureTimestamp: string;
}

export interface CapturedImage {
  file: File;
  previewUrl: string;
  gps: GpsCoordinates | null;
  deviceMeta: DeviceMeta;
  capturedAt: string;
}

interface CameraCaptureProps {
  onCapture: (images: CapturedImage[]) => void;
  isLoading: boolean;
  onCameraUnavailable?: () => void;
}

type GpsStatus = "acquiring" | "available" | "denied" | "unavailable";

function acquireGps(): Promise<GpsCoordinates | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 0 }
    );
  });
}

export function CameraCapture({
  onCapture,
  isLoading,
  onCameraUnavailable,
}: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [captures, setCaptures] = useState<CapturedImage[]>([]);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [gpsStatus, setGpsStatus] = useState<GpsStatus>("acquiring");
  const [facingMode, setFacingMode] = useState<"environment" | "user">(
    "environment"
  );
  const [isCapturing, setIsCapturing] = useState(false);

  // Start camera stream
  const startStream = useCallback(
    async (facing: "environment" | "user") => {
      // Stop existing stream
      streamRef.current?.getTracks().forEach((t) => t.stop());

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facing },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
        setCameraReady(true);
        setCameraError(null);
      } catch (err) {
        const name = (err as DOMException)?.name;
        if (name === "NotAllowedError") {
          setCameraError(
            "Pristup kameri odbijen. Omogucite pristup kameri u postavkama preglednika."
          );
        } else if (name === "NotFoundError") {
          setCameraError("Kamera nije pronadena na ovom uredaju.");
          onCameraUnavailable?.();
        } else {
          setCameraError("Greska pri pokretanju kamere.");
          onCameraUnavailable?.();
        }
      }
    },
    []
  );

  // Init camera + probe GPS
  useEffect(() => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Vas preglednik ne podrzava pristup kameri. Koristite moderan preglednik (Chrome, Safari, Firefox).");
      onCameraUnavailable?.();
      return;
    }

    startStream(facingMode);

    // Probe GPS status
    if (!navigator.geolocation) {
      setGpsStatus("unavailable");
    } else {
      navigator.geolocation.getCurrentPosition(
        () => setGpsStatus("available"),
        () => setGpsStatus("denied"),
        { enableHighAccuracy: true, timeout: 3000, maximumAge: 60000 }
      );
    }

    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Switch camera
  const handleSwitchCamera = useCallback(() => {
    const next = facingMode === "environment" ? "user" : "environment";
    setFacingMode(next);
    startStream(next);
  }, [facingMode, startStream]);

  // Capture photo
  const handleShutter = useCallback(async () => {
    if (!videoRef.current || !canvasRef.current || isCapturing) return;
    if (captures.length >= MAX_IMAGES) return;

    setIsCapturing(true);

    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setIsCapturing(false);
      return;
    }
    ctx.drawImage(video, 0, 0);

    // Get GPS and blob in parallel
    const [gps, blob] = await Promise.all([
      acquireGps(),
      new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.92)
      ),
    ]);

    if (gps) setGpsStatus("available");

    if (!blob) {
      setIsCapturing(false);
      return;
    }

    const timestamp = new Date().toISOString();
    const file = new File([blob], `capture_${Date.now()}.jpg`, {
      type: "image/jpeg",
    });

    const track = streamRef.current?.getVideoTracks()[0];

    const captured: CapturedImage = {
      file,
      previewUrl: URL.createObjectURL(blob),
      gps,
      deviceMeta: {
        userAgent: navigator.userAgent,
        cameraLabel: track?.label || "unknown",
        screenWidth: window.screen.width,
        screenHeight: window.screen.height,
        captureTimestamp: timestamp,
      },
      capturedAt: timestamp,
    };

    setCaptures((prev) => [...prev, captured]);
    setIsCapturing(false);
  }, [captures.length, isCapturing]);

  // Remove capture
  const removeCapture = useCallback((index: number) => {
    setCaptures((prev) => {
      const removed = prev[index];
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }, []);

  // Submit
  const handleSubmit = () => {
    if (captures.length > 0) onCapture(captures);
  };

  // Retry camera
  const handleRetry = useCallback(() => {
    setCameraError(null);
    setCameraReady(false);
    startStream(facingMode);
  }, [facingMode, startStream]);

  // Error state — camera is mandatory, no upload fallback
  if (cameraError) {
    return (
      <div className="border-2 border-dashed border-amber-300 bg-amber-50/50 rounded-xl p-8 text-center space-y-4">
        <div className="w-14 h-14 rounded-xl bg-amber-100 flex items-center justify-center mx-auto">
          <svg
            className="w-7 h-7 text-amber-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z"
            />
          </svg>
        </div>
        <div>
          <p className="text-sm text-foreground font-semibold mb-1">Kamera nije dostupna</p>
          <p className="text-sm text-amber-800">{cameraError}</p>
        </div>
        <p className="text-xs text-muted max-w-sm mx-auto">
          Za maksimalnu forenzicku pouzdanost koristite uredaj s kamerom.
          Alternativne opcije su dostupne ispod.
        </p>
        <button
          onClick={handleRetry}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-accent text-white rounded-lg font-medium text-sm hover:bg-accent-hover transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
          </svg>
          Pokusaj ponovo
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Viewfinder */}
      <div className="relative rounded-xl overflow-hidden bg-black">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full aspect-video object-cover"
        />
        <canvas ref={canvasRef} className="hidden" />

        {/* GPS indicator */}
        <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-black/50 backdrop-blur-sm rounded-full px-2.5 py-1">
          <div
            className={cn(
              "w-2 h-2 rounded-full",
              gpsStatus === "available" && "bg-green-400",
              gpsStatus === "acquiring" && "bg-yellow-400 animate-pulse",
              (gpsStatus === "denied" || gpsStatus === "unavailable") &&
                "bg-red-400"
            )}
          />
          <span className="text-[10px] text-white/80 font-medium">GPS</span>
        </div>

        {/* Loading overlay when not ready */}
        {!cameraReady && (
          <div className="absolute inset-0 flex items-center justify-center bg-black">
            <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Controls bar */}
      <div className="flex items-center justify-between px-2">
        <span className="text-sm text-muted min-w-[5rem]">
          {captures.length}/{MAX_IMAGES} slika
        </span>

        {/* Shutter button */}
        <button
          onClick={handleShutter}
          disabled={
            !cameraReady ||
            isCapturing ||
            isLoading ||
            captures.length >= MAX_IMAGES
          }
          className={cn(
            "w-16 h-16 rounded-full border-4 border-accent flex items-center justify-center transition-all",
            !cameraReady || isCapturing || captures.length >= MAX_IMAGES
              ? "opacity-40 cursor-not-allowed"
              : "hover:scale-105 active:scale-95"
          )}
        >
          <div
            className={cn(
              "w-12 h-12 rounded-full bg-white transition-colors",
              isCapturing && "bg-gray-300"
            )}
          />
        </button>

        {/* Camera switch */}
        <button
          onClick={handleSwitchCamera}
          disabled={!cameraReady || isLoading}
          className="w-10 h-10 rounded-full bg-card border border-border flex items-center justify-center hover:bg-accent/10 transition-colors disabled:opacity-40"
        >
          <svg
            className="w-5 h-5 text-foreground"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"
            />
          </svg>
        </button>
      </div>

      {/* GPS warning */}
      {gpsStatus === "denied" && (
        <p className="text-xs text-amber-600 text-center">
          GPS lokacija odbijena. Fotografije nece sadrzavati lokaciju.
        </p>
      )}
      {gpsStatus === "unavailable" && (
        <p className="text-xs text-amber-600 text-center">
          GPS nije dostupan na ovom uredaju.
        </p>
      )}

      {/* Thumbnail grid */}
      {captures.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted">
              {captures.length}/{MAX_IMAGES} slika
            </span>
            {!isLoading && (
              <button
                onClick={() => {
                  captures.forEach((c) => URL.revokeObjectURL(c.previewUrl));
                  setCaptures([]);
                }}
                className="text-xs text-muted hover:text-red-500 transition-colors"
              >
                Ukloni sve
              </button>
            )}
          </div>
          <div className="grid grid-cols-4 gap-2">
            {captures.map((cap, i) => (
              <div
                key={i}
                className="relative group aspect-square rounded-lg overflow-hidden border border-border"
              >
                <img
                  src={cap.previewUrl}
                  alt={`Snimka ${i + 1}`}
                  className="w-full h-full object-cover"
                />
                {!isLoading && (
                  <button
                    onClick={() => removeCapture(i)}
                    className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <svg
                      className="w-3 h-3"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                )}
                {i === 0 && (
                  <div className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded text-[9px] bg-accent text-white font-medium">
                    Glavna
                  </div>
                )}
                {cap.gps && (
                  <div className="absolute bottom-1 right-1 w-4 h-4 rounded-full bg-green-500/80 flex items-center justify-center">
                    <svg
                      className="w-2.5 h-2.5 text-white"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Submit button */}
      {captures.length > 0 && (
        <button
          onClick={handleSubmit}
          disabled={isLoading}
          className={cn(
            "w-full py-3 rounded-lg font-medium text-sm transition-colors",
            isLoading
              ? "bg-gray-100 text-muted cursor-wait"
              : "bg-accent text-white hover:bg-accent-hover"
          )}
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Analiziranje...
            </span>
          ) : (
            `Analiziraj ${captures.length} ${captures.length === 1 ? "sliku" : captures.length < 5 ? "slike" : "slika"}`
          )}
        </button>
      )}
    </div>
  );
}
