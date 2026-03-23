# main.py
import os
from insight_entry import InsightEntry

def main():

    if "QDF_API_KEY" not in os.environ or "QDF_API_URL" not in os.environ:
        print("Error: Please set QDF_API_KEY and QDF_API_URL environments.")
        return

    # 创建分析器实例
    analyzer = InsightEntry(
        model_name="gpt-4.1-nano",
        base_savedir="./outputs",
        temperature=0.1,
        n_retries=1,
        branch_depth=1,
        max_questions=1
    )

    sample_data_dir = "./insight/sample_data/flag-99/output"
    insights, summary = analyzer.analyze_folder(sample_data_dir)
    
    print("\n=== Analysis Results ===")
    print(f"Summary: {summary}")
    print("\nInsights:")
    for i, insight in enumerate(insights, 1):
        print(f"{i}. {insight}")
    
    return insights, summary

if __name__ == "__main__":
    main()