import { authenticatedPharos } from "@/lib/pharos";

export async function GET() {
  return authenticatedPharos("/v1/documents");
}

export async function POST(request: Request) {
  return authenticatedPharos("/v1/documents", {
    method: "POST",
    body: await request.formData(),
  });
}
