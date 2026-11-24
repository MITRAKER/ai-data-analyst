import { connection } from "next/server";

import { AnalystApp } from "@/components/AnalystApp";

export default async function Home() {
  // Render this page for each request, never ahead of time, so that it gets
  // the fresh nonce that src/proxy.ts puts in the Content-Security-Policy.
  await connection();
  return <AnalystApp />;
}
