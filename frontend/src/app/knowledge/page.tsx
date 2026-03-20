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

export default function KnowledgePage() {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function fetchDocs() {
    setLoading(true);
    try {
      const result = await listKnowledgeDocuments();
      setDocs(result);
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
      alert(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
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
          <div className="flex items-center justify-center py-12 text-gray-400">
            <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mr-2" />
            Loading…
          </div>
        ) : docs.length === 0 ? (
          <div className="py-12 text-center text-sm text-gray-400">
            No documents indexed yet. Upload a file above.
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
