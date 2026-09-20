import { NextResponse } from "next/server";
import { authenticatedPharos } from "@/lib/pharos";

export async function PATCH(
  request: Request,
  context: RouteContext<"/api/documents/[documentId]/access">,
) {
  const { documentId } = await context.params;
  if (!documentId || documentId.length > 255) {
    return NextResponse.json({ status: "bad_arg" }, { status: 400 });
  }
  return authenticatedPharos(`/v1/documents/${encodeURIComponent(documentId)}/access`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
