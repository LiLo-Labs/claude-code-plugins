import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  'client',
  {
    test: {
      include: ['hooks/lib/**/*.test.js'],
      name: 'hooks',
    },
  },
  {
    test: {
      include: ['hooks/integration.test.js'],
      name: 'integration',
      testTimeout: 30000,
    },
  },
  {
    test: {
      include: ['hooks/e2e.test.js'],
      name: 'e2e',
      testTimeout: 45000,
    },
  },
  {
    test: {
      include: ['server/**/*.test.js'],
      name: 'server',
    },
  },
]);
