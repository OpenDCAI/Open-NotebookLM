import React, { useState } from 'react';
import { Sparkles, Loader2, AlertCircle } from 'lucide-react';
import { apiFetch } from '../../config/api';
import { getApiSettings } from '../../services/apiSettingsService';

interface FlashcardGeneratorProps {
  selectedFiles: string[];
  notebookId: string;
  email: string;
  userId: string;
  onGenerated: (flashcardSetId: string, flashcards: any[]) => void;
}

export const FlashcardGenerator: React.FC<FlashcardGeneratorProps> = ({
  selectedFiles,
  notebookId,
  email,
  userId,
  onGenerated,
}) => {
  const [loading, setLoading] = useState(false);
  const [cardCount, setCardCount] = useState(20);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (selectedFiles.length === 0) {
      setError('Please select at least one file');
      return;
    }

    // 获取 API 配置
    const settings = getApiSettings(userId);
    if (!settings?.apiUrl || !settings?.apiKey) {
      setError('Please configure API URL and API Key in Settings first');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await apiFetch('/api/v1/kb/generate-flashcards', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file_paths: selectedFiles,
          notebook_id: notebookId,
          email: email,
          user_id: userId,
          api_url: settings.apiUrl,
          api_key: settings.apiKey,
          model: 'deepseek-v3.2',
          card_count: cardCount,
          language: 'en',
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('API Error:', errorText);
        throw new Error(`API request failed: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success && data.flashcards) {
        onGenerated(data.flashcard_set_id, data.flashcards);
      } else {
        setError('Failed to generate flashcards');
      }
    } catch (err: any) {
      console.error('Generate flashcards error:', err);
      setError(err.message || 'Failed to generate flashcards');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 bg-white rounded-lg shadow-sm border">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="w-5 h-5 text-purple-600" />
        <h3 className="text-lg font-semibold">Generate Flashcards</h3>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded flex items-start gap-2">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Selected Files: {selectedFiles.length}
        </label>
        <p className="text-xs text-gray-500">
          Extract key knowledge points from selected files to generate flashcards
        </p>
      </div>

      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Number of Cards
        </label>
        <input
          type="number"
          value={cardCount}
          onChange={(e) => setCardCount(Number(e.target.value))}
          min={5}
          max={50}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <p className="text-xs text-gray-500 mt-1">
          Recommended: 10-30 cards
        </p>
      </div>

      <button
        onClick={handleGenerate}
        disabled={loading || selectedFiles.length === 0}
        className="w-full bg-purple-600 text-white py-2.5 px-4 rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-colors"
      >
        {loading ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <Sparkles className="w-4 h-4" />
            Generate Flashcards
          </>
        )}
      </button>
    </div>
  );
};
