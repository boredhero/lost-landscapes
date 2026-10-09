import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

/** Mount only while work is pending, so each operation gets its own elapsed clock. */
export default function LoadingNotice({ label }: { label: string }) {
  const [started] = useState(() => Date.now());
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [started]);
  return <div className="loading-notice" role="status">
    <LoaderCircle className="spin" size={18} aria-hidden="true" />
    <span><strong>{label}</strong>{seconds >= 8 && <small>Taking longer than usual. You can keep exploring.</small>}</span>
    <span className="loading-elapsed" aria-hidden="true">{seconds}s</span>
  </div>;
}
