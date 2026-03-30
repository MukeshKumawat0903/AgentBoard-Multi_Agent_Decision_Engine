/**
 * Knowledge base management page.
 * Upload, list, and delete documents from the RAG knowledge base.
 */

"use client";

import { useState, useEffect, useRef } from "react";
import {
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
  deleteKnowledgeDocument,
} from "@/lib/api";
import type { KnowledgeDocument } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { SkeletonList } from "@/components/Skeleton";

export default function KnowledgePage() {
  const { showToast } = useToast();
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function fetchDocs() {
    setLoading(true);
    setFetchError(null);
    try {
      const result = await listKnowledgeDocuments();
      setDocs(result);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to load documents.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchDocs(); }, []);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      await uploadKnowledgeDocument(file);
      await fetchDocs();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(name: string) {
    setDeleteTarget(name);
    try {
      await deleteKnowledgeDocument(name);
      setDocs((prev) => prev.filter((d) => d.name !== name));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Delete failed.", "error");
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8 animate-fadeIn">
      <div>
        <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-1">Knowledge Base</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Upload documents (PDF, TXT, Markdown) so agents can retrieve relevant context during debates.
        </p>
      </div>

      {/* Upload card */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Upload Document</h2>
        <div
          onClick={() => fileInputRef.current?.click()}
          className="flex flex-col items-center justify-center border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-8 cursor-pointer
                     hover:border-blue-400 dark:hover:border-blue-600 transition-colors"
        >
          {uploading ? (
            <span className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-2" />
          ) : (
            <span className="text-3xl mb-2">📄</span>
          )}
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {uploading ? "Uploading…" : "Click to upload PDF, TXT, or Markdown (max 10 MB)"}
          </p>
          {uploadError && (
            <p className="text-xs text-red-500 mt-2">{uploadError}</p>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,.md"
          className="hidden"
          onChange={handleFileChange}
          disabled={uploading}
        />
      </div>

      {/* Document list */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border dark:border-gray-800 shadow-sm">
        <div className="px-6 py-4 border-b dark:border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
            Indexed Documents
          </h2>
          <button
            onClick={fetchDocs}
            disabled={loading}
            className="text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        {loading ? (
          <SkeletonList count={3} className="px-4 py-4" />
        ) : fetchError ? (
          <div className="py-8 text-center space-y-3">
            <p className="text-sm text-red-500 dark:text-red-400">{fetchError}</p>
            <button
              onClick={fetchDocs}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
            >
              Retry
            </button>
          </div>
        ) : docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 gap-4 text-center">
            <svg width="56" height="56" viewBox="0 0 56 56" fill="none" aria-hidden="true">
              <rect width="56" height="56" rx="14" className="fill-gray-100 dark:fill-gray-800" />
              <rect x="16" y="12" width="24" height="30" rx="3" className="fill-gray-300 dark:fill-gray-600" />
              <rect x="20" y="18" width="16" height="2" rx="1" className="fill-white dark:fill-gray-500" />
              <rect x="20" y="23" width="12" height="2" rx="1" className="fill-white dark:fill-gray-500" />
              <rect x="20" y="28" width="14" height="2" rx="1" className="fill-white dark:fill-gray-500" />
              <circle cx="38" cy="38" r="9" className="fill-blue-500" />
              <path d="M38 34v8M34 38h8" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">No documents indexed yet</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">Upload a PDF, TXT, or Markdown file above to get started.</p>
            </div>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              Upload a document
            </button>
          </div>
        ) : (
          <ul className="divide-y dark:divide-gray-800">
            {docs.map((doc) => (
              <li key={doc.name} className="px-6 py-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-lg shrink-0">
                    {doc.name.endsWith(".pdf") ? "📄" : doc.name.endsWith(".md") ? "📝" : "📃"}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-300 truncate font-medium">
                      {doc.name}
                    </p>
                    <p className="text-xs text-gray-400">
                      {doc.chunks} chunk{doc.chunks !== 1 ? "s" : ""} indexed
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(doc.name)}
                  disabled={deleteTarget === doc.name}
                  className="shrink-0 text-xs px-3 py-1.5 rounded-lg border border-red-300 dark:border-red-700
                             text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20
                             disabled:opacity-50 transition"
                >
                  {deleteTarget === doc.name ? "Deleting…" : "Delete"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
