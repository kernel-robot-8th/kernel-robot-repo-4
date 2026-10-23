import type { MessageMap, MessageName } from "@/generated/messages";

// 메시지마다 모의 데이터 파일 하나(<이름>.json, 배열)다. 정의와 맞는지는 파이썬 시험(test_gen_web_types.py)이 본다.
// 서버(게이트웨이)가 붙으면 같은 모양의 배열을 받는다: 대상 하나(로봇·팔·카메라)마다 최신 값 하나.
const files = import.meta.glob<unknown>("./*.json", { eager: true, import: "default" });

export function getMock<K extends MessageName>(name: K): MessageMap[K][] {
  const data = files[`./${name}.json`];
  if (!Array.isArray(data)) {
    throw new Error(`모의 데이터가 없다: src/mock/${name}.json (gen_web_types --init-mocks 로 만든다)`);
  }
  return data as MessageMap[K][];
}
