import { Outlet } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';

export function EditorRoute() {
  const isEditor = useAuthStore((s) => s.isEditor());

  if (!isEditor) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <h1 className="text-4xl font-bold">403</h1>
        <p className="mt-2 text-muted-foreground">
          Forbidden -- Editor or Admin access required
        </p>
      </div>
    );
  }

  return <Outlet />;
}
