import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'in.gov.nirikshan.monitoring',
  appName: 'Nirikshan',
  webDir: 'www',
  server: {
    url: 'https://real-time-monitoring-inspection-system.onrender.com',
    cleartext: false
  },
  android: {
    allowMixedContent: false
  }
};

export default config;
