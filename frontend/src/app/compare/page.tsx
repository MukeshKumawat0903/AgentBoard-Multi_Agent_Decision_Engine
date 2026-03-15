/**
 * Compare page - side-by-side comparison of two debate decisions.
 * Route: /compare?a=<thread_id>&b=<thread_id>
 *
 * useSearchParams is used inside CompareContent (a separate client component)
 * so it can be correctly wrapped in Suspense per Next.js App Router requirements.
 */

import { Suspense } from "react";
import CompareContent from "@/components/CompareContent";

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-500">Loading...</div>}>
      <CompareContent />
    </Suspense>
  );
}
