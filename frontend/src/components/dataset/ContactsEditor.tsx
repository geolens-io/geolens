import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { X, Loader2 } from 'lucide-react';
import { useContacts, useCreateContact, useDeleteContact } from '@/components/dataset/hooks/use-records';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';

interface ContactsEditorProps {
  recordId: string;
  canEdit: boolean;
}

const ROLE_OPTIONS = [
  { value: 'pointOfContact', labelKey: 'contacts.roles.pointOfContact' },
  { value: 'author', labelKey: 'contacts.roles.author' },
  { value: 'publisher', labelKey: 'contacts.roles.publisher' },
  { value: 'distributor', labelKey: 'contacts.roles.distributor' },
  { value: 'custodian', labelKey: 'contacts.roles.custodian' },
] as const;

export function ContactsEditor({ recordId, canEdit }: ContactsEditorProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useContacts(recordId);
  const createContact = useCreateContact(recordId);
  const deleteContact = useDeleteContact(recordId);

  const [role, setRole] = useState('pointOfContact');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [organization, setOrganization] = useState('');
  const [showForm, setShowForm] = useState(false);

  const handleAdd = async () => {
    if (!name.trim()) return;
    try {
      await createContact.mutateAsync({
        role,
        name: name.trim(),
        email: email.trim() || null,
        organization: organization.trim() || null,
      });
      toast.success(t('contacts.added'));
      setName('');
      setEmail('');
      setOrganization('');
      setRole('pointOfContact');
      setShowForm(false);
    } catch {
      toast.error(t('contacts.addFailed'));
    }
  };

  const handleDelete = async (contactId: string) => {
    try {
      await deleteContact.mutateAsync(contactId);
      toast.success(t('contacts.removed'));
    } catch {
      toast.error(t('contacts.removeFailed'));
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const contacts = data?.contacts ?? [];

  const showContactForm = canEdit && (contacts.length > 0 || showForm);

  return (
    <div className="space-y-3">
      {contacts.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('contacts.noContacts')}</p>
      )}

      {contacts.length === 0 && canEdit && !showForm && (
        <Button variant="outline" size="sm" onClick={() => setShowForm(true)}>
          {t('contacts.addContact')}
        </Button>
      )}

      {contacts.map((contact) => (
        <div
          key={contact.id}
          className="flex items-center gap-2 text-sm border rounded-md px-3 py-2"
        >
          <Badge variant="outline" className="shrink-0">{contact.role}</Badge>
          <span className="font-medium">{contact.name}</span>
          {contact.email && (
            <span className="text-muted-foreground">{contact.email}</span>
          )}
          {contact.organization && (
            <span className="text-muted-foreground">{contact.organization}</span>
          )}
          {canEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto h-6 w-6 p-0"
              onClick={() => handleDelete(contact.id)}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ))}

      {showContactForm && (
        <div className="space-y-2 border rounded-md p-3 bg-muted/30">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">{t('contacts.role')}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {t(opt.labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('contacts.name')}</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-8"
                placeholder={t('contacts.name')}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('contacts.email')}</Label>
              <Input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-8"
                placeholder={t('contacts.email')}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('contacts.organization')}</Label>
              <Input
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                className="h-8"
                placeholder={t('contacts.organization')}
              />
            </div>
          </div>
          <Button
            size="sm"
            onClick={handleAdd}
            disabled={!name.trim() || createContact.isPending}
          >
            {createContact.isPending && <Loader2 className="h-3.5 w-3.5 me-1 animate-spin" />}
            {t('contacts.addContact')}
          </Button>
        </div>
      )}
    </div>
  );
}
