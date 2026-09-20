import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const SESSION_COOKIE = "pharos_key";

const baseUrl = process.env.PHAROS_API_URL ?? "http://127.0.0.1:8787";

export async function sessionKey(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

export async function callPharos(
  path: string,
  key: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", key);
  return fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(120_000),
  });
}

export function relay(response: Response): Promise<NextResponse> {
  return response.text().then((body) =>
    new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    }),
  );
}

export async function authenticatedPharos(
  path: string,
  init: RequestInit = {},
): Promise<NextResponse> {
  const key = await sessionKey();
  if (!key) {
    return NextResponse.json({ status: "unauthorized", hint: "请先连接知识库。" }, { status: 401 });
  }
  try {
    return await relay(await callPharos(path, key, init));
  } catch {
    return NextResponse.json(
      { status: "backend_unavailable", hint: "后端暂时不可用，请确认 Pharos 服务已启动。" },
      { status: 503 },
    );
  }
}
