import type { Metadata } from "next";
import { Space_Grotesk, Inter, Inter_Tight, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { MobileNav } from "@/components/MobileNav";
import { Footer } from "@/components/Footer";
import { AuthProvider } from "@/lib/auth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ScrollProvider } from "@/components/ScrollProvider";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin", "latin-ext"],
  display: "swap",
});

const interTight = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500"],
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
    <html lang="hr" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var d=document.documentElement;var t=localStorage.getItem("dent_theme");if(t==="dark")d.classList.add("dark");if(localStorage.getItem("dent_token"))d.dataset.auth="1"}catch(e){}})()`,
          }}
        />
      </head>
      <body
        className={`${inter.variable} ${interTight.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} antialiased bg-background text-foreground`}
      >
        <AuthProvider>
          <ScrollProvider>
            <Navbar />
            <main className="min-h-[calc(100dvh-56px)] pb-20 md:pb-0">
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
            </main>
            <Footer />
            <MobileNav />
          </ScrollProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
