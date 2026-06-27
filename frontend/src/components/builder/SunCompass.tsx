/**
 * builder-audit COMPLEX-01: the hillshade sun-position compass, extracted out of
 * DEMEditorScene's main render where it was ~55 lines of inline-styled absolutely
 * positioned divs. Presentational only — the parent owns the azimuth state and the
 * accessible label.
 */
export interface SunCompassProps {
  /** Illumination direction in degrees (0–360); drives the needle rotation. */
  azimuth: number;
  /** Accessible label, e.g. "Sun azimuth: 135°". */
  ariaLabel: string;
}

export function SunCompass({ azimuth, ariaLabel }: SunCompassProps) {
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="relative mx-auto mb-3"
      style={{
        width: '90px',
        height: '90px',
        borderRadius: '50%',
        border: '1px solid var(--border)',
        background: 'radial-gradient(circle, var(--surface-1), var(--surface-2))',
      }}
    >
      {/* N-S crosshair */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: 0,
          bottom: 0,
          width: '1px',
          background: 'var(--border)',
          transform: 'translateX(-50%)',
        }}
      />
      {/* E-W crosshair */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: 0,
          right: 0,
          height: '1px',
          background: 'var(--border)',
          transform: 'translateY(-50%)',
        }}
      />
      {/* Needle */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          width: '2px',
          height: '38px',
          background: 'var(--primary)',
          transformOrigin: 'center bottom',
          transform: `translate(-50%, -100%) rotate(${azimuth}deg)`,
          borderRadius: '1px',
        }}
      />
    </div>
  );
}
