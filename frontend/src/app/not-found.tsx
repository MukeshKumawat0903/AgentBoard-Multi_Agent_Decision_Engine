import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-lg mx-auto text-center py-24 space-y-6 px-4">
      <div className="text-6xl font-black text-gray-200 dark:text-gray-700">404</div>
      <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">
        Page not found
      </h1>
      <p className="text-gray-500 dark:text-gray-400 text-sm">
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <div className="flex items-center justify-center gap-3">
        <Link
          href="/"
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition"
        >
          Start a debate
        </Link>
        <Link
          href="/history"
          className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 transition"
        >
          View history
        </Link>
      </div>
    </div>
  );
}
