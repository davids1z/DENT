"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-[400px] flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="text-6xl mb-4">!</div>
            <h2 className="text-xl font-semibold text-foreground mb-2">
              Nesto je poslo krivo
            </h2>
            <p className="text-muted mb-6">
              Doslo je do neocekivane greske. Pokusajte osvjeziti stranicu.
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
            >
              Pokusajte ponovo
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
