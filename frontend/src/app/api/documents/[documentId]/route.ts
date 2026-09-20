import { NextResponse } from "next/server";
import { authenticatedPharos } from "@/lib/pharos";

function pathFor(documentId: string) {
  if (!documentId || documentId.length > 255 || documentId === "." || documentId === "..") return null;
  return `/v1/documents/${encodeURIComponent(documentId)}`;
}

export async function GET(
  _request: Request,
  context: RouteContext<"/api/documents/[documentId]">,
) {
  const path = pathFor((await context.params).documentId);
  if (!path) return NextResponse.json({ status: "bad_arg" }, { status: 400 });
  return authenticatedPharos(`${path}?max_tokens=12000`);
}

export async function DELETE(
  _request: Request,
  context: RouteContext<"/api/documents/[documentId]">,
) {
  const path = pathFor((await context.params).documentId);
  if (!path) return NextResponse.json({ status: "bad_arg" }, { status: 400 });
  return authenticatedPharos(path, { method: "DELETE" });
}
