/** 가격을 '89,000원' 처럼 쓴다. */
export function formatPrice(won: number): string {
  return `${won.toLocaleString("ko-KR")}원`;
}
