import { useCallback, useEffect, useRef, useState } from "react";
import { IngestionTask, getTaskStatus } from "../api/client";

const POLL_INTERVAL = 1500;

export function useIngestionTask() {
  const [task, setTask] = useState<IngestionTask | null>(null);
  const [polling, setPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setPolling(false);
  }, []);

  const startPolling = useCallback(
    (taskId: string) => {
      stopPolling();
      setPolling(true);

      const poll = async () => {
        try {
          const status = await getTaskStatus(taskId);
          setTask(status);
          if (status.status === "completed" || status.status === "failed") {
            stopPolling();
          }
        } catch {
          stopPolling();
        }
      };

      // Fetch immediately, then on interval
      poll();
      intervalRef.current = setInterval(poll, POLL_INTERVAL);
    },
    [stopPolling]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return { task, polling, startPolling, stopPolling };
}
