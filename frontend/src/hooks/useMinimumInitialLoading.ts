import { useEffect, useRef, useState } from "react";

const MINIMUM_SKELETON_DURATION_MS = 350;

export default function useMinimumInitialLoading(loading: boolean) {
  const startedAt = useRef(Date.now());
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (loading || !visible) return;

    const remaining = Math.max(
      0,
      MINIMUM_SKELETON_DURATION_MS - (Date.now() - startedAt.current),
    );
    const timeoutId = window.setTimeout(() => setVisible(false), remaining);
    return () => window.clearTimeout(timeoutId);
  }, [loading, visible]);

  return visible;
}
