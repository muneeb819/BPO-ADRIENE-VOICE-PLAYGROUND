/*
 * Adriene Voice Studio - application configuration
 *
 * SECURITY NOTE
 * Anything in this file is shipped to the browser and is therefore public.
 * The key below was supplied with the original prototype. Rotate it in the
 * Deepgram console before publishing this site, and in production route
 * speech requests through a small backend proxy so the key never reaches
 * the client.
 */
window.ADRIENE_CONFIG = {
    deepgramApiKey: "",
    defaultVoice: "aura-asteria-en",
    sttUrl: "wss://api.deepgram.com/v1/listen?model=nova-2&punctuate=true&interim_results=true&smart_format=true"
};
