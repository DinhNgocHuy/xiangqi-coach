import { useState } from "react";
import { Sidebar, type Page } from "./components/Sidebar";
import { useBackendStatus } from "./hooks/useBackendStatus";
import { useScreenCapture } from "./hooks/useScreenCapture";
import { useSession } from "./hooks/useSession";
import { DashboardPage } from "./pages/DashboardPage";
import { JournalPage } from "./pages/JournalPage";
import { MoveReviewPage } from "./pages/MoveReviewPage";
import { ScreenMonitorPage } from "./pages/ScreenMonitorPage";
import { TrainingPage } from "./pages/TrainingPage";
import { buildMoveReview } from "./services/moveReview";
import type { MoveReview } from "./types/moveReview";

// ponytail: pages switch by state; add react-router when deep links or >5 screens are needed.
export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const capture = useScreenCapture();
  const backend = useBackendStatus();
  const session = useSession();
  const [sampleSessionId] = useState(() => crypto.randomUUID());
  // Sample mode only ("Chế độ mẫu"): those reviews stay in memory and are never sent to the backend.
  const [sampleReviews, setSampleReviews] = useState<MoveReview[]>([]);

  return (
    <div className="flex h-full bg-slate-950 text-slate-200">
      <Sidebar page={page} onNavigate={setPage} status={capture.status} backend={backend} />
      <main className="flex-1 overflow-y-auto p-8">
        {page === "dashboard" && <DashboardPage capture={capture} onOpenMonitor={() => setPage("monitor")} />}
        {page === "monitor" && <ScreenMonitorPage capture={capture} session={session} />}
        {page === "review" && (
          <MoveReviewPage
            session={session}
            reviews={sampleReviews}
            onAddReview={(played, sa) => setSampleReviews((r) => [...r, buildMoveReview(sampleSessionId, played, sa)])}
          />
        )}
        {page === "journal" && <JournalPage />}
        {page === "training" && <TrainingPage />}
      </main>
    </div>
  );
}
