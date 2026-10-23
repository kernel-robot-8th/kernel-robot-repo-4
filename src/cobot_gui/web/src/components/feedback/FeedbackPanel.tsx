import { useState, useEffect, useCallback } from "react";
import { useLocation } from "react-router-dom";
import {
  MessageSquare,
  X,
  Plus,
  Trash2,
  Download,
  Filter,
  CheckCircle,
  Lightbulb,
  AlertTriangle,
  HelpCircle,
  RefreshCw,
  HardDrive,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { findMenu } from "@/lib/registry";

export interface FeedbackItem {
  id: string;
  menuId: string;
  menuName: string;
  author: string;
  category: "suggestion" | "bug" | "ux" | "question";
  content: string;
  createdAt: string;
}

const STORAGE_KEY = "fms_menu_feedback_v1";
const AUTHOR_STORAGE_KEY = "fms_feedback_author";

const CATEGORY_MAP: Record<
  FeedbackItem["category"],
  { label: string; tone: string; icon: typeof Lightbulb }
> = {
  suggestion: { label: "기능 제안", tone: "bg-blue-900/60 text-blue-300 border-blue-700", icon: Lightbulb },
  bug: { label: "버그/결함", tone: "bg-red-900/60 text-red-300 border-red-700", icon: AlertTriangle },
  ux: { label: "UI/UX", tone: "bg-purple-900/60 text-purple-300 border-purple-700", icon: CheckCircle },
  question: { label: "질문/확인", tone: "bg-amber-900/60 text-amber-300 border-amber-700", icon: HelpCircle },
};

export default function FeedbackPanel() {
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(true);
  const [isServerSynced, setIsServerSynced] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [items, setItems] = useState<FeedbackItem[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Current active menu detection
  const match = location.pathname.match(/\/menus\/([^/]+)/);
  const currentMenuId = match ? match[1] : null;
  const currentMenu = currentMenuId ? findMenu(currentMenuId) : null;
  const currentMenuTitle = currentMenu ? `${currentMenu.id} ${currentMenu.name}` : (currentMenuId ?? "전체 화면");

  // Form states
  const [author, setAuthor] = useState(() => localStorage.getItem(AUTHOR_STORAGE_KEY) || "");
  const [category, setCategory] = useState<FeedbackItem["category"]>("suggestion");
  const [content, setContent] = useState("");
  const [filterCurrentMenuOnly, setFilterCurrentMenuOnly] = useState(true);

  // Fetch feedback from server flat-file
  const fetchServerFeedback = useCallback(async () => {
    if (typeof window === "undefined" || !window.location || !window.location.host || window.location.protocol === "file:") {
      return;
    }
    setIsSyncing(true);
    try {
      const res = await fetch("/api/feedback");
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setItems(data);
          localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
          setIsServerSynced(true);
        }
      }
    } catch {
      // quiet fallback in non-browser or test environments
      setIsServerSynced(false);
    } finally {
      setIsSyncing(false);
    }
  }, []);

  useEffect(() => {
    fetchServerFeedback();
  }, [fetchServerFeedback]);

  // Sync to local storage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch (e) {
      console.error("Failed to save feedback to localStorage", e);
    }
  }, [items]);

  const handleAddFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;

    const trimmedAuthor = author.trim() || "익명";
    localStorage.setItem(AUTHOR_STORAGE_KEY, trimmedAuthor);

    const newItem: FeedbackItem = {
      id: `fb-${Date.now()}`,
      menuId: currentMenuId || "global",
      menuName: currentMenuTitle,
      author: trimmedAuthor,
      category,
      content: content.trim(),
      createdAt: new Date().toISOString(),
    };

    // Optimistic UI update
    setItems((prev) => [newItem, ...prev]);
    setContent("");

    // Send to server flat-file API
    if (typeof window !== "undefined" && window.location?.host && window.location.protocol !== "file:") {
      try {
        const res = await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newItem),
        });
        if (res.ok) {
          setIsServerSynced(true);
        }
      } catch {
        setIsServerSynced(false);
      }
    }
  };

  const handleDelete = async (id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));

    if (typeof window !== "undefined" && window.location?.host && window.location.protocol !== "file:") {
      try {
        await fetch(`/api/feedback?id=${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
      } catch {
        // quiet fallback
      }
    }
  };

  // Export to Markdown
  const handleExportMarkdown = () => {
    if (items.length === 0) {
      alert("내보낼 피드백이 없습니다.");
      return;
    }

    let md = `# FMS 메뉴별 피드백 및 개선 요구사항 리포트\n\n`;
    md += `* 추출 시각: ${new Date().toLocaleString()}\n`;
    md += `* 총 피드백 건수: ${items.length}건\n`;
    md += `* 영속 저장 위치: \`src/cobot_gui/web/src/data/fms_feedback.json\` (Git 관리)\n\n---\n\n`;

    const grouped: Record<string, FeedbackItem[]> = {};
    for (const item of items) {
      if (!grouped[item.menuName]) grouped[item.menuName] = [];
      grouped[item.menuName].push(item);
    }

    for (const [menuName, list] of Object.entries(grouped)) {
      md += `## 📌 ${menuName} (${list.length}건)\n\n`;
      for (const item of list) {
        const cat = CATEGORY_MAP[item.category].label;
        const time = new Date(item.createdAt).toLocaleString();
        md += `* **[${cat}]** ${item.author} (${time})\n`;
        md += `  > ${item.content.replace(/\n/g, "\n  > ")}\n\n`;
      }
    }

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `fms_feedback_report_${Date.now()}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const filteredItems = filterCurrentMenuOnly && currentMenuId
    ? items.filter((item) => item.menuId === currentMenuId)
    : items;

  const currentMenuCount = currentMenuId
    ? items.filter((item) => item.menuId === currentMenuId).length
    : items.length;

  return (
    <>
      {/* Floating Toggle Button (Visible when closed) */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 border border-border bg-card px-4 py-2.5 text-xs font-medium text-foreground shadow-lg hover:bg-muted"
        >
          <MessageSquare className="h-4 w-4 text-primary" />
          <span>메뉴 피드백</span>
          <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
            {currentMenuCount}
          </Badge>
        </button>
      )}

      {/* Slide-out / Right-side Panel */}
      <aside
        className={`fixed top-0 right-0 z-40 h-screen w-80 md:w-96 border-l border-border bg-card transition-transform duration-200 ease-in-out flex flex-col ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border p-4 bg-muted/40">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold tracking-tight">메뉴별 피드백</h2>
            <Badge variant="outline" className="text-[11px] font-mono">
              {filteredItems.length}건
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchServerFeedback}
              title="서버 데이터 새로고침"
              disabled={isSyncing}
              className="h-8 w-8 p-0"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isSyncing ? "animate-spin" : ""}`} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleExportMarkdown}
              title="Markdown 리포트 다운로드"
              className="h-8 px-2 text-xs"
            >
              <Download className="h-3.5 w-3.5 mr-1" />
              내보내기
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsOpen(false)}
              className="h-8 w-8 p-0"
              title="닫기"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Sync Status Badge Bar */}
        <div className="bg-muted/60 px-4 py-1.5 border-b border-border flex items-center justify-between text-[11px] text-muted-foreground font-mono">
          <span className="flex items-center gap-1.5">
            <HardDrive className="h-3 w-3" />
            <span>저장: fms_feedback.json</span>
          </span>
          <span className={`inline-flex items-center gap-1 ${isServerSynced ? "text-emerald-400" : "text-amber-400"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${isServerSynced ? "bg-emerald-400" : "bg-amber-400"}`} />
            {isServerSynced ? "Git 연동 동기화됨" : "로컬 보관"}
          </span>
        </div>

        {/* Current Target Menu & Filter Bar */}
        <div className="border-b border-border bg-background px-4 py-2.5 text-xs flex items-center justify-between gap-2">
          <div className="truncate font-mono font-medium text-foreground">
            🎯 {currentMenuTitle}
          </div>
          <button
            onClick={() => setFilterCurrentMenuOnly(!filterCurrentMenuOnly)}
            className={`flex items-center gap-1 border px-2 py-1 text-[11px] ${
              filterCurrentMenuOnly
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-border text-muted-foreground hover:bg-muted"
            }`}
            title="현재 메뉴만 보기 / 전체 보기 토글"
          >
            <Filter className="h-3 w-3" />
            {filterCurrentMenuOnly ? "이 메뉴만" : "전체 보기"}
          </button>
        </div>

        {/* Input Form */}
        <form onSubmit={handleAddFeedback} className="border-b border-border p-4 space-y-3 bg-muted/20">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                작성자
              </label>
              <input
                type="text"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="이름 (예: 김성아, 멘토)"
                className="w-full border border-border bg-background px-2.5 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                required
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                유형
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as FeedbackItem["category"])}
                className="w-full border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="suggestion">💡 기능 제안</option>
                <option value="bug">🐛 버그/결함</option>
                <option value="ux">🎨 UI/UX</option>
                <option value="question">💬 질문/확인</option>
              </select>
            </div>
          </div>

          <div>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={`[${currentMenuTitle}]에 대한 피드백, 누락된 기능, 제안 사항을 적어주세요...`}
              rows={3}
              className="w-full border border-border bg-background p-2.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none"
              required
            />
          </div>

          <Button type="submit" size="sm" className="w-full h-8 text-xs font-medium">
            <Plus className="h-3.5 w-3.5 mr-1" />
            피드백 등록 (파일 영속 저장)
          </Button>
        </form>

        {/* Feedback List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {filteredItems.length === 0 ? (
            <div className="py-12 text-center text-xs text-muted-foreground">
              <MessageSquare className="mx-auto mb-2 h-6 w-6 opacity-30" />
              <p>작성된 피드백이 없습니다.</p>
              <p className="mt-1 text-[11px]">위 폼에서 첫 피드백을 남겨보세요!</p>
            </div>
          ) : (
            filteredItems.map((item) => {
              const cat = CATEGORY_MAP[item.category];
              return (
                <div
                  key={item.id}
                  className="border border-border bg-background p-3 text-xs space-y-2 relative group"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`inline-flex items-center border px-1.5 py-0.5 text-[10px] font-medium ${cat.tone}`}>
                        {cat.label}
                      </span>
                      <span className="font-semibold text-foreground">{item.author}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {new Date(item.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity p-0.5"
                      title="삭제"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {!filterCurrentMenuOnly && (
                    <div className="text-[10px] text-muted-foreground font-mono">
                      📌 {item.menuName}
                    </div>
                  )}

                  <p className="whitespace-pre-wrap text-foreground/90 leading-relaxed break-words">
                    {item.content}
                  </p>
                </div>
              );
            })
          )}
        </div>
      </aside>
    </>
  );
}
