import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

export default function LoadingNotice({ label, details }: { label: string; details?: string[] }) {
  const [started] = useState(() => Date.now());
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [started]);
  const content = <><LoaderCircle className="spin" size={13} aria-hidden="true" />
    <span>{label}</span><span className="loading-elapsed" aria-hidden="true">{seconds}s</span></>;
  return details?.length ? <details className="loading-notice">
    <summary aria-label={`${label}; show loading details`}>{content}</summary>
    <ul>{details.map(item => <li key={item}>{item}</li>)}</ul>
  </details> : <div className="loading-notice" role="status">{content}</div>;
}
