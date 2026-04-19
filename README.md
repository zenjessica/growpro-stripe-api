# GrowPro Stripe Checkout API

A single serverless function that creates dynamic Stripe Checkout sessions for the GrowPro configurators.

## Setup

1. Deploy to Vercel
2. Add environment variable: `STRIPE_KEY` = your Stripe restricted key
3. The API endpoint will be: `https://your-project.vercel.app/api/create-checkout`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `STRIPE_KEY` | Stripe restricted API key with Checkout Sessions, Products, and Prices write permissions |
