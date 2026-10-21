declare module 'draco3d/draco_decoder_nodejs.js' {
  const createDecoderModule: (options?: Record<string, unknown>) => Promise<unknown>;
  export default createDecoderModule;
}
