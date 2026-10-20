/* Deepgram TTS voice catalog — shared by Voice Lab and Agent Studio */
'use strict';

(function () {
  const flux = [
    { id: 'flux-hannah-en', name: 'Hannah', accent: 'American', gender: 'feminine' },
    { id: 'flux-kit-en', name: 'Kit', accent: 'British', gender: 'masculine' },
    { id: 'flux-alexis-en', name: 'Alexis', accent: 'American', gender: 'feminine' },
    { id: 'flux-cliff-en', name: 'Cliff', accent: 'American', gender: 'masculine' },
    { id: 'flux-sienna-en', name: 'Sienna', accent: 'American', gender: 'feminine' },
    { id: 'flux-cole-en', name: 'Cole', accent: 'American', gender: 'masculine' },
    { id: 'flux-brooke-en', name: 'Brooke', accent: 'American', gender: 'feminine' },
    { id: 'flux-colin-en', name: 'Colin', accent: 'British', gender: 'masculine' },
    { id: 'flux-gemma-en', name: 'Gemma', accent: 'British', gender: 'feminine' },
    { id: 'flux-haley-en', name: 'Haley', accent: 'American', gender: 'feminine' },
    { id: 'flux-heather-en', name: 'Heather', accent: 'American', gender: 'feminine' },
    { id: 'flux-miles-en', name: 'Miles', accent: 'American', gender: 'masculine' },
    { id: 'flux-sean-en', name: 'Sean', accent: 'British', gender: 'masculine' },
    { id: 'flux-bree-en', name: 'Bree', accent: 'American', gender: 'feminine' },
    { id: 'flux-brittany-en', name: 'Brittany', accent: 'American', gender: 'feminine' },
    { id: 'flux-bruce-en', name: 'Bruce', accent: 'American', gender: 'masculine' },
    { id: 'flux-conor-en', name: 'Conor', accent: 'British', gender: 'masculine' },
    { id: 'flux-donovan-en', name: 'Donovan', accent: 'American', gender: 'masculine' },
    { id: 'flux-drew-en', name: 'Drew', accent: 'American', gender: 'masculine' },
    { id: 'flux-elise-en', name: 'Elise', accent: 'American', gender: 'feminine' },
    { id: 'flux-jack-en', name: 'Jack', accent: 'British', gender: 'masculine' },
    { id: 'flux-kai-en', name: 'Kai', accent: 'Singaporean', gender: 'masculine' },
    { id: 'flux-kelsey-en', name: 'Kelsey', accent: 'American', gender: 'feminine' },
    { id: 'flux-maeve-en', name: 'Maeve', accent: 'Irish', gender: 'feminine' },
    { id: 'flux-marcelo-en', name: 'Marcelo', accent: 'Filipino', gender: 'masculine' },
    { id: 'flux-marcus-en', name: 'Marcus', accent: 'American', gender: 'masculine' },
    { id: 'flux-meena-en', name: 'Meena', accent: 'Indian', gender: 'feminine' },
    { id: 'flux-meghan-en', name: 'Meghan', accent: 'American', gender: 'feminine' },
    { id: 'flux-naveen-en', name: 'Naveen', accent: 'Indian', gender: 'masculine' },
    { id: 'flux-paige-en', name: 'Paige', accent: 'American', gender: 'feminine' },
    { id: 'flux-priya-en', name: 'Priya', accent: 'Indian', gender: 'feminine' },
    { id: 'flux-rufus-en', name: 'Rufus', accent: 'British', gender: 'masculine' },
    { id: 'flux-sharon-en', name: 'Sharon', accent: 'Australian', gender: 'feminine' },
    { id: 'flux-tanner-en', name: 'Tanner', accent: 'British', gender: 'masculine' },
    { id: 'flux-wade-en', name: 'Wade', accent: 'American', gender: 'masculine' },
    { id: 'flux-wes-en', name: 'Wes', accent: 'American', gender: 'masculine' },
  ].map((voice) => ({ ...voice, family: 'Flux' }));

  const aura = [
    { id: 'aura-asteria-en', name: 'Asteria', accent: 'American', gender: 'feminine' },
    { id: 'aura-luna-en', name: 'Luna', accent: 'American', gender: 'feminine' },
    { id: 'aura-stella-en', name: 'Stella', accent: 'American', gender: 'feminine' },
    { id: 'aura-orion-en', name: 'Orion', accent: 'American', gender: 'masculine' },
    { id: 'aura-arcas-en', name: 'Arcas', accent: 'American', gender: 'masculine' },
  ].map((voice) => ({ ...voice, family: 'Aura' }));

  const all = [...flux, ...aura];

  window.VOICE_CATALOG = {
    flux,
    aura,
    all,
    byId: (id) => all.find((voice) => voice.id === id) || null,
  };
})();
