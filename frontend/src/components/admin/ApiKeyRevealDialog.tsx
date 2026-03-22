import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ApiKeyCreateResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Copy, Check } from 'lucide-react';

interface ApiKeyRevealDialogProps {
  apiKey: ApiKeyCreateResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ApiKeyRevealDialog({ apiKey, open, onOpenChange }: ApiKeyRevealDialogProps) {
  const { t } = useTranslation('admin');
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(apiKey.key);
    } catch {
      // Fallback for environments where clipboard API is unavailable
      const textarea = document.createElement('textarea');
      textarea.value = apiKey.key;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('apiKeyReveal.title')}</DialogTitle>
          <DialogDescription>
            {t('apiKeyReveal.description')}
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded bg-muted p-3 font-mono text-sm break-all select-all">
            {apiKey.key}
          </code>
          <Button variant="outline" size="sm" onClick={handleCopy}>
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </Button>
        </div>
        <p className="text-sm text-destructive font-medium">
          {t('apiKeyReveal.warning')}
        </p>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>{t('apiKeyReveal.done')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
