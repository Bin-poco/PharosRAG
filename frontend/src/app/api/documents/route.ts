import { authenticatedPharos } from "@/lib/pharos";

export async function GET() {
  return authenticatedPharos("/v1/documents");
}

export async function POST(request: Request) {
  const idempotencyKey = request.headers.get("idempotency-key");
  return authenticatedPharos("/v1/documents", {
    method: "POST",
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    body: await request.formData(),
  });
}
