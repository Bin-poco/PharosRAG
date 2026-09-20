import { NextResponse } from "next/server";
import { callPharos, relay, SESSION_COOKIE, sessionKey } from "@/lib/pharos";

export async function GET() {
  const key = await sessionKey();
  if (!key) {
    return NextResponse.json({ status: "unauthorized" }, { status: 401 });
  }
  try {
    const response = await callPharos("/v1/me", key);
    const result = await relay(response);
    if (response.status === 401) result.cookies.delete(SESSION_COOKIE);
    return result;
  } catch {
    return NextResponse.json(
      { status: "backend_unavailable", hint: "连接不到 Pharos 后端。" },
      { status: 503 },
    );
  }
}

export async function POST(request: Request) {
  let key: unknown;
  try {
    key = (await request.json()).key;
  } catch {
    return NextResponse.json({ status: "bad_arg", hint: "请输入 API Key。" }, { status: 400 });
  }
  if (typeof key !== "string" || !key.trim() || key.length > 512) {
    return NextResponse.json({ status: "bad_arg", hint: "请输入有效的 API Key。" }, { status: 400 });
  }
  try {
    const response = await callPharos("/v1/me", key.trim());
    const result = await relay(response);
    if (response.ok) {
      result.cookies.set(SESSION_COOKIE, key.trim(), {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "strict",
        path: "/",
      });
    }
    return result;
  } catch {
    return NextResponse.json(
      { status: "backend_unavailable", hint: "连接不到 Pharos 后端。" },
      { status: 503 },
    );
  }
}

export async function DELETE() {
  const response = NextResponse.json({ status: "ok" });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
