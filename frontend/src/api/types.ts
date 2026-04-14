export type DiffMode = "working_tree" | "commit_range" | "refs_compare";
export type AnalysisStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
export type Confidence = "high" | "medium" | "low";
export type SymbolKind =
  | "module"
  | "class"
  | "function"
  | "async_function"
  | "method"
  | "async_method"
  | "staticmethod"
  | "classmethod"
  | "test_function"
  | "test_method";

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string;
  };
}

export interface RepositoryCreateInput {
  name: string;
  repo_path: string;
  main_branch?: string;
}

export interface RepositoryRead {
  repository_id: string;
  name: string;
  repo_path: string;
  main_branch: string;
  language: "python";
  created_at: string;
}

export interface AnalysisOptions {
  max_depth: number;
  include_tests: boolean;
  use_coverage: boolean;
}

export interface AnalysisCreateInput {
  repository_id: string;
  diff_mode: DiffMode;
  commit_from?: string | null;
  commit_to?: string | null;
  base_ref?: string | null;
  head_ref?: string | null;
  include_untracked: boolean;
  options: AnalysisOptions;
}

export interface AnalysisAccepted {
  analysis_id: string;
  repository_id: string;
  status: AnalysisStatus;
  created_at: string;
}

export interface AnalysisSummary {
  changed_files: number;
  changed_python_files: number;
  changed_symbols: number;
  unmapped_changes: number;
  impacted_symbols: number;
  top_impacts: number;
  high_confidence_impacts: number;
  impacted_tests: number;
  propagation_paths: number;
  recommended_tests: number;
  skipped_files: number;
  parse_failures: number;
  scanned_files: number;
  parsed_files: number;
  parse_failed_files: number;
  extracted_symbols: number;
  extracted_edges: number;
}

export interface EvidenceItem {
  edge_type: string;
  file_path: string | null;
  line: number | null;
  detail: string;
}

export interface ReasonsJson {
  source_symbol: string;
  matched_from_changed_symbol: string;
  edge_types: string[];
  path_length: number;
  hop_count: number;
  merged_paths_count: number;
  is_test_symbol: boolean;
  contributing_changed_symbols: string[];
  evidence: EvidenceItem[];
}

export interface ImpactItem {
  symbol_id: string;
  symbol_key: string;
  symbol_name: string;
  symbol_kind: SymbolKind;
  file_path: string;
  score: number;
  confidence: Confidence;
  reasons: string[];
  explanation_path: string[];
  reasons_json: ReasonsJson;
}

export interface WarningMessage {
  code: string;
  message: string;
}

export interface AnalysisResult {
  analysis_id: string;
  repository_id: string;
  status: AnalysisStatus;
  summary: AnalysisSummary;
  impacts: ImpactItem[];
  warnings: WarningMessage[];
}

export interface RecentAnalysisItem {
  analysis_id: string;
  repository_id: string;
  created_at: string;
}
