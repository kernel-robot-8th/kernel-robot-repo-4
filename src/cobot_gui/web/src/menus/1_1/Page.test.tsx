import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("1.1 전체 로봇 현황", () => {
  it("핑키 3대와 팔 3대를 보인다", () => {
    render(<Page menu={findMenu("1.1")!} />);
    for (const id of ["pinky_1", "pinky_2", "pinky_3", "omx_1", "omx_2", "omx_3"]) {
      expect(screen.getByLabelText(id)).toBeInTheDocument();
    }
    expect(within(screen.getByLabelText("pinky_1")).getByText("NAVIGATING")).toBeInTheDocument();
    expect(screen.getAllByText("모의 데이터")).toHaveLength(2);
  });

  it("미측정 배터리를 0 % 로 채우지 않는다", () => {
    render(<Page menu={findMenu("1.1")!} />);
    const card = screen.getByLabelText("pinky_3");
    expect(within(card).getByText("미측정")).toBeInTheDocument();
    expect(within(card).queryByText(/0 %/)).not.toBeInTheDocument();
    expect(within(card).getByText("PROXIMITY")).toBeInTheDocument();
    expect(within(screen.getByLabelText("pinky_1")).getByText("79 %")).toBeInTheDocument();
  });

  it("맵 지문이 모두 일치한다고 보인다", () => {
    render(<Page menu={findMenu("1.1")!} />);
    expect(screen.getAllByText("일치")).toHaveLength(3);
  });

  it("퇴피를 재지 못한 팔은 통과로 보이지 않는다", () => {
    render(<Page menu={findMenu("1.1")!} />);
    expect(within(screen.getByLabelText("omx_2")).getByText("미측정 (통과 아님)")).toBeInTheDocument();
    expect(within(screen.getByLabelText("omx_2")).getByText("LEROBOT_EXCLUSIVE")).toBeInTheDocument();
    expect(within(screen.getByLabelText("omx_1")).getByText("완료")).toBeInTheDocument();
    expect(within(screen.getByLabelText("omx_3")).getByText("HUMAN_IN_ZONE")).toBeInTheDocument();
  });
});
