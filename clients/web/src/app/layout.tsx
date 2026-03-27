import type { Metadata } from "next";
import { Space_Grotesk, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { MobileNav } from "@/components/MobileNav";
import { Footer } from "@/components/Footer";
import { AuthProvider } from "@/lib/auth";
import { ErrorBoundary } from "@/components/ErrorBoundary";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const plusJakarta = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "DENT - Detekcija prijevara i forenzička verifikacija",
  description:
    "AI platforma za detekciju prijevara, forenzičku analizu slika i dokumenata, prepoznavanje AI-generiranog sadržaja i kriptografsku verifikaciju dokaza.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="hr">
      <body
        className={`${plusJakarta.variable} ${spaceGrotesk.variable} antialiased bg-background text-foreground`}
      >
        <AuthProvider>
          <Navbar />
          <main className="min-h-[calc(100vh-64px)] pb-20 md:pb-0">
            <ErrorBoundary>
              {children}
            </ErrorBoundary>
          </main>
          <div className="hidden md:block">
            <Footer />
          </div>
          <MobileNav />
        </AuthProvider>
      </body>
    </html>
  );
}
