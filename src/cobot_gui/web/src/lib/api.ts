// 홈랩 관리자 화면의 fetchAPI 와 같은 서명이다. 메뉴 화면은 이 함수만 거쳐 서버를 부른다.
// 그래서 홈랩으로 메뉴 폴더를 옮길 때 기준 주소(VITE_API_BASE)와 프록시만 맞추면 된다.

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

export async function fetchAPI<T = unknown>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}: ${endpoint}`);
  }
  return (await res.json()) as T;
}
