import { AnalystApp } from "@/components/AnalystApp";

// The layout makes every page render per request, with a fresh nonce.
export default function Home() {
  return <AnalystApp />;
}
