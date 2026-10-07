import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Routes, Route } from "react-router-dom";
import LandscapePage from "./pages/LandscapePage";
import { lazy, Suspense } from "react";
const PlaygroundPage = lazy(() => import("./pages/PlaygroundPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route path="/" element={<LandscapePage />} />
        <Route
          path="/playground"
          element={
            <Suspense fallback={<p>Loading analysis tools…</p>}>
              <PlaygroundPage />
            </Suspense>
          }
        />
      </Routes>
    </QueryClientProvider>
  );
}
