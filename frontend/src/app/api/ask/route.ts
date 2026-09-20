import { authenticatedPharos } from "@/lib/pharos";

export async function POST(request: Request) {
  return authenticatedPharos("/v1/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
