import { useCallback, useEffect, useRef, useState } from "react";
import { IngestionTask, getTaskStatus } from "../api/client";

const BASE_INTERVAL = 1500;
const MAX_INTERVAL = 30000;

export function useIngestionTask() {
  const [task, setTask] = useState<IngestionTask | null>(null);
  const [polling, setPolling] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errorCountRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setPolling(false);
  }, []);

  const startPolling = useCallback(
    (taskId: string) => {
      stopPolling();
      setPolling(true);
      errorCountRef.current = 0;

      const poll = async () => {
        try {
          const status = await getTaskStatus(taskId);
          setTask(status);
          errorCountRef.current = 0;
          if (status.status === "completed" || status.status === "failed") {
            setPolling(false);
          } else {
            timeoutRef.current = setTimeout(poll, BASE_INTERVAL);
          }
        } catch {
          errorCountRef.current += 1;
          const backoff = Math.min(
            BASE_INTERVAL * Math.pow(2, errorCountRef.current),
            MAX_INTERVAL
          );
          timeoutRef.current = setTimeout(poll, backoff);
        }
      };

      // Fetch immediately, then chain via setTimeout
      poll();
    },
    [stopPolling]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return { task, polling, startPolling, stopPolling };
}
