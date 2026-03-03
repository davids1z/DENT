import type { Metadata } from "next";
import { DM_Sans, Outfit } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { MobileNav } from "@/components/MobileNav";
import { Footer } from "@/components/Footer";

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin", "latin-ext"],
  display: "swap",
});

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin", "latin-ext"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "DENT - AI analiza šteta na vozilima",
  description:
    "AI platforma za detekciju oštećenja vozila, klasifikaciju ozbiljnosti i procjenu troškova popravka. Uploadajte fotografije i dobijte profesionalni izvještaj.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="hr">
      <body
        className={`${dmSans.variable} ${outfit.variable} antialiased bg-background text-foreground`}
      >
        <Navbar />
        <main className="min-h-[calc(100vh-64px)] pb-20 md:pb-0">
          {children}
        </main>
        <div className="hidden md:block">
          <Footer />
        </div>
        <MobileNav />
      </body>
    </html>
  );
}
