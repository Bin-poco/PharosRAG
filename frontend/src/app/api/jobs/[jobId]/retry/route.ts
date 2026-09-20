import { NextResponse } from "next/server";
import { authenticatedPharos } from "@/lib/pharos";

export async function POST(
  _request: Request,
  context: RouteContext<"/api/jobs/[jobId]/retry">,
) {
  const { jobId } = await context.params;
  if (!/^job_[a-zA-Z0-9_-]+$/.test(jobId)) {
    return NextResponse.json({ status: "bad_arg" }, { status: 400 });
  }
  return authenticatedPharos(`/v1/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
}
