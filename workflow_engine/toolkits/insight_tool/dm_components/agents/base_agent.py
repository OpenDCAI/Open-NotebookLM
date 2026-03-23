import os
import json
import copy
import tempfile
from PIL import Image


from dm_components import prompts
from dm_components.config import logger
from dm_components.utils import agent_utils as au
from dm_components.utils.dataloader_utils import DataSourceReader

from langchain.schema import HumanMessage, SystemMessage    



class AgentBase:
    def __init__(
        self,
        savedir=None,
        context="This is a dataset that could potentially consist of interesting insights",
        model_name="gpt-3.5-turbo-0613",
        goal="I want to find interesting trends in this dataset",
        verbose=False,
        temperature=0,
        n_retries=2,
        dataset_path=None,
        api_key=None,
        base_url=None
    ):
        self.goal = goal
        if savedir is None:
            savedir = tempfile.mkdtemp()
        self.savedir = savedir
        self.context = context

        self.model_name = model_name
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url

        self.insights_history = []
        self.verbose = verbose
        self.n_retries = n_retries
        self.schema = None
        self.dataset_path = dataset_path
        self.multi_schema = None
        self.multi_dataset_path = None
        self.multi_profile = None  # NEW: Support for profile information in multi-dataset scenarios

    def set_table(
        self,
        table=None,
        multi_table=None,
        dataset_path=None,  # 从 dataset_csv_path 重命名
        multi_dataset_path=None,  # 从 multi_dataset_csv_path 重命名
        dataset_read_kwargs=None,
        multi_dataset_read_kwargs=None,
    ):
        
        if dataset_read_kwargs is None:
            dataset_read_kwargs = {}
        if multi_dataset_read_kwargs is None:
            multi_dataset_read_kwargs = {}

        # 1. 始终存储路径。它们对执行上下文是必要的。
        # 保持变量名称（self.dataset_path）不变
        # 因为 answer_question 函数依赖于它们。
        self.dataset_path = dataset_path 
        self.multi_dataset_path = multi_dataset_path

        # --- 主表逻辑 ---
        if table is not None:
            self.table = table
        elif dataset_path is not None:
            # 优先级 2: 如果没有传递 DataFrame，则从路径加载
            logger.info(f"未提供 DataFrame，正在从路径加载: {dataset_path}")
            try:
                self.table = DataSourceReader.read_data(dataset_path, **dataset_read_kwargs)  #
            except Exception as e:
                logger.error(f"从 {dataset_path} 读取数据失败: {e}")
                raise
        else:
            self.table = None  # 未提供数据

        if self.table is None:
            raise ValueError("AgentBase.set_table: no 'table' provided.")
            
        self.schema = au.get_schema(self.table)
        


    def summarize(self, pred_insights, method="list", prompt_summarize_method="basic"):
        if method == "list":
            chat = au.get_chat_model(self.model_name, self.temperature, self.api_key, self.base_url)

            # Function to format the data
            def format_data(data):
                result = ""
                for i, item in enumerate(data):
                    question_tag = f"<question_{i}>{item['question']}</question_{i}>\n"
                    answer_tag = f"<answer_{i}>{item['answer']}</answer_{i}>\n\n"
                    result += f"{question_tag} {answer_tag}\n"
                return result

            # Format the data and print
            formatted_history = format_data(pred_insights)

            # summary = agent.summarize_insights(method="list")
            content_prompt, system_prompt = prompts.get_summarize_prompt(
                method=prompt_summarize_method
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=content_prompt.format(
                        context=self.context,
                        goal=self.goal,
                        history=formatted_history,
                    )
                ),
            ]

            def _validate_tasks(out):
                isights = au.extract_html_tags(out, ["insight"])

                # Check that there are insights generated
                if "insight" not in isights:
                    return (
                        out,
                        False,
                        f"Error: you did not generate insights within the <insight></insight> tags.",
                    )
                isights = isights["insight"]
                return (isights, out), True, ""

            insight_list, message = au.chat_and_retry(
                chat, messages, n_retry=3, parser=_validate_tasks
            )

            insights = "\n".join(insight_list)

        return insights

    def select_a_question(self, questions):
        """
        Select a question from the list of questions
        """
        return au.select_a_question(
            questions,
            self.context,
            self.goal,
            [o["question"] for o in self.insights_history],
            self.model_name,
            prompts.SELECT_A_QUESTION_TEMPLATE,
            prompts.SELECT_A_QUESTION_SYSTEM_MESSAGE,
        )

    def generate_notebook():
        pass

    def generate_report():
        pass

    def recommend_questions(
        self,
        n_questions=3,
        insights_history=None,
        prompt_method=None,
        question_type=None,
    ):
        """
        Suggest Next Best Questions
        """
        if self.verbose:
            print(f"Generating {n_questions} Questions using {self.model_name}...")

        if insights_history is None:

            # Generate Root Questions
            questions = au.get_questions(
                prompt_method=prompt_method,
                context=self.context,
                goal=self.goal,
                messages=[],
                schema=self.schema,
                max_questions=n_questions,
                model_name=self.model_name,
                temperature=self.temperature,
            )
        else:
            # Generate Follow Up Questions
            last_insight = insights_history[-1]
            questions = au.get_follow_up_questions(
                context=self.context,
                goal=self.goal,
                question=last_insight["question"],
                answer=last_insight["answer"],
                schema=self.schema,
                max_questions=n_questions,
                model_name=self.model_name,
                prompt_method=prompt_method,
                question_type=question_type,
                temperature=self.temperature,
            )
            if self.verbose:
                print(
                    "\nFollowing up on the last insight:\n---------------------------------"
                )
                print(f"Question: {last_insight['question']}\n")
                print(f"Answer: {last_insight['answer']}\n")

        if self.verbose:
            print("\nNext Best Questions:\n-------------------")
            for idx, question in enumerate(questions):
                print(f"{idx+1}. {question}")
            print()

        return questions

    def answer_question(
        self,
        question,
        n_retries=2,
        return_insight_dict=True,
        prompt_code_method="single",
        prompt_interpret_method="interpret",
    ):
        n_retries = self.n_retries
        if self.verbose:
            print(f"Generating Code...")
        
        code_output_folder = os.path.join(
            self.savedir, f"question_{str(len(self.insights_history))}"
        )

        if self.verbose:
            print(f"Interpreting Solution...")
            print(f"Results saved at: {self.savedir}")

        multi_path_processed = None
        if self.multi_dataset_path is not None:
            if isinstance(self.multi_dataset_path, list):
                # 如果是路径列表，对每个路径应用 abspath
                multi_path_processed = [os.path.abspath(p) for p in self.multi_dataset_path]
            elif isinstance(self.multi_dataset_path, str):
                # 如果是单个路径字符串，直接应用 abspath (保持向后兼容)
                multi_path_processed = os.path.abspath(self.multi_dataset_path)

        solution = au.generate_code(
            schema=self.schema,
            multi_schema=self.multi_schema,
            goal=self.goal,
            question=question,
            database_path=os.path.abspath(self.dataset_path) if self.dataset_path else None,
            # 使用上面处理好的变量
            multi_database_path=multi_path_processed,
            output_folder=code_output_folder,
            model_name=self.model_name,
            n_retries=n_retries,
            prompt_method=prompt_code_method,
            temperature=self.temperature,
            multi_profile=self.multi_profile,  # NEW: Pass profile information
        )

        # Prompt 4: Interpret Solution
        interpretation_dict = au.interpret_solution(
            solution=solution,
            model_name=self.model_name,
            schema=self.schema,
            n_retries=n_retries,
            prompt_method=prompt_interpret_method,
            temperature=self.temperature,
        )
        answer = interpretation_dict["interpretation"]["answer"]

        if self.verbose:
            print("\nSolution\n---------")
            print(f"Question: {question}\n")
            print(f"Answer: {answer}\n")
            print(
                f"Justification: {interpretation_dict['interpretation']['justification']}\n"
            )

        insight_dict = {
            "question": question,
            "answer": answer,
            "insight": interpretation_dict["interpretation"]["insight"],
            "justification": interpretation_dict["interpretation"]["justification"],
            "output_folder": code_output_folder,
        }

        # Save into the savedir
        os.makedirs(code_output_folder, exist_ok=True) # 确保目录存在
        with open(os.path.join(code_output_folder, "insight.json"), "w", encoding='utf-8') as json_file:
            json.dump(insight_dict, json_file, indent=4, sort_keys=True, ensure_ascii=False)

        # add to insights
        self.insights_history += [insight_dict]

        insight_dict = copy.deepcopy(insight_dict)
        insight_dict.update(self.get_insight_objects(insight_dict))

        if return_insight_dict:
            return answer, insight_dict

        return answer["answer"]

        
    def get_insight_objects(self, insight_dict):
        """
        Get Insight Objects
        """
        if os.path.exists(os.path.join(insight_dict["output_folder"], "plot.jpg")):
            # get plot.jpg
            plot = Image.open(os.path.join(insight_dict["output_folder"], "plot.jpg"))
        else:
            plot = None

        if os.path.exists(os.path.join(insight_dict["output_folder"], "x_axis.jpg")):
            # get x_axis.json
            x_axis = json.load(
                open(os.path.join(insight_dict["output_folder"], "x_axis.json"), "r")
            )
        else:
            x_axis = None

        if os.path.exists(os.path.join(insight_dict["output_folder"], "y_axis.json")):
            # get y_axis.json
            y_axis = json.load(
                open(os.path.join(insight_dict["output_folder"], "y_axis.json"), "r")
            )
        else:
            y_axis = None

        if os.path.exists(os.path.join(insight_dict["output_folder"], "stat.json")):
            try:
                # get stat.json
                stat = json.load(
                    open(os.path.join(insight_dict["output_folder"], "stat.json"), "r")
                )
            except:
                stat = None
        else:
            stat = None

        # get code.py
        if os.path.exists(os.path.join(insight_dict["output_folder"], "code.py")):
            code = open(
                os.path.join(insight_dict["output_folder"], "code.py"), "r"
            ).read()
        else:
            code = None

        insight_object = {
            "plot": plot,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "stat": stat,
            "code": code,
        }
        return insight_object

    def save_state_dict(self, fname):
        with open(fname, "w", encoding='utf-8') as f:
            json.dump(self.insights_history, f, indent=4, ensure_ascii=False)

    def load_state_dict(self, fname):
        with open(fname, "r") as f:
            self.insights_history = json.load(f)

