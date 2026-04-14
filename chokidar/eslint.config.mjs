import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import { defineConfig } from 'eslint/config';

export default defineConfig([
    {
        files: ['**/*.{js,mjs,cjs,ts,mts,cts}'],
        plugins: {
            js,
        },
        extends: ['js/recommended'],
        languageOptions: {
            globals: globals.node,
        },
    },
    {
        files: ['**/*.js'],
        languageOptions: {
            sourceType: 'commonjs',
        },
    },
    tseslint.configs.recommended,
    {
        rules: {
            '@typescript-eslint/no-require-imports': 'off',
            'array-bracket-spacing': 'error',
            'brace-style': 'error',
            'comma-dangle': ['error', 'always-multiline'],
            'comma-spacing': 'error',
            'computed-property-spacing': 'error',
            curly: 'error',
            'dot-notation': 'error',
            'eol-last': 'error',
            eqeqeq: 'error',
            'func-call-spacing': 'error',
            indent: [
                'error', 4, {
                    SwitchCase: 1,
                },
            ],
            'keyword-spacing': 'error',
            'linebreak-style': 'error',
            'no-constructor-return': 'error',
            'no-multi-spaces': ['error', { ignoreEOLComments: true }],
            'no-multiple-empty-lines': ['error', { max: 1 }],
            'no-tabs': 'error',
            'no-template-curly-in-string': 'error',
            'no-trailing-spaces': 'error',
            'no-var': 'error',
            'no-whitespace-before-property': 'error',
            'object-curly-spacing': ['error', 'always'],
            'one-var-declaration-per-line': ['error', 'always'],
            'prefer-const': 'error',
            'quote-props': ['error', 'as-needed'],
            quotes: ['error', 'single'],
            'padded-blocks': ['error', 'never'],
            semi: ['error', 'always'],
            'space-before-blocks': 'error',
            'space-before-function-paren': ['error', 'never'],
            'space-in-parens': 'error',
            'space-infix-ops': 'error',
        },
    },
]);
