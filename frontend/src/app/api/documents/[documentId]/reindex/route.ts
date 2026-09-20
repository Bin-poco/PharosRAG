import { NextResponse } from "next/server";
import { authenticatedPharos } from "@/lib/pharos";

export async function POST(
  _request: Request,
  context: RouteContext<"/api/documents/[documentId]/reindex">,
) {
  const { documentId } = await context.params;
  if (!documentId || documentId.length > 255) {
    return NextResponse.json({ status: "bad_arg" }, { status: 400 });
  }
  return authenticatedPharos(`/v1/documents/${encodeURIComponent(documentId)}/reindex`, {
    method: "POST",
  });
}
