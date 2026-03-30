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
      include: ['server/**/*.test.js'],
      name: 'server',
    },
  },
]);
