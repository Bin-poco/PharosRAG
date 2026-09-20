import { authenticatedPharos } from "@/lib/pharos";

export async function GET() {
  return authenticatedPharos("/v1/uploads");
}
