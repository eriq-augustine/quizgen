import copy
import json5
import math
import os

import quizgen.common
import quizgen.constants
import quizgen.parser
import quizgen.util.file

PROMPT_FILENAME = 'prompt.md'

class Question(object):
    def __init__(self, prompt = '', question_type = '', answers = [],
            base_dir = '.',
            points = 0, base_name = '',
            **kwargs):
        self.base_dir = base_dir

        self.prompt = prompt
        self.prompt_document = None

        self.question_type = question_type

        self.answers = answers
        self.answers_documents = None

        self.points = points
        self.base_name = base_name

        try:
            self.validate()
        except Exception as ex:
            raise quizgen.common.QuizValidationError(f"Error while validating question.") from ex

    def validate(self):
        if ((self.prompt is None) or (self.prompt == "")):
            raise quizgen.common.QuizValidationError("Prompt cannot be empty.")
        self.prompt_document = quizgen.parser.parse_text(self.prompt, base_dir = self.base_dir)

        if (self.question_type not in quizgen.constants.QUESTION_TYPES):
            raise quizgen.common.QuizValidationError(f"Unknown question type: '{self.question_type}'.")

        self._validate_answers()

    def _validate_answers(self):
        if (self.question_type in [quizgen.constants.QUESTION_TYPE_ESSAY, quizgen.constants.QUESTION_TYPE_TEXT_ONLY]):
            if (not isinstance(self.answers, list)):
                raise quizgen.common.QuizValidationError("Question type '%s' cannot have answers." % (self.question_type))

            if (len(self.answers) != 0):
                raise quizgen.common.QuizValidationError("Question type '%s' cannot have answers." % (self.question_type))
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_FIMB):
            self._validate_fimb_answers()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_MATCHING):
            self._validate_matching_answers()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_MA):
            self._validate_answer_list()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_MCQ):
            self._validate_answer_list(min_correct = 1, max_correct = 1)
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_MDD):
            self._validate_mdd_answers()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_NUMERICAL):
            self._validate_numerical_answers()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_SA):
            self._validate_fitb_answers()
        elif (self.question_type == quizgen.constants.QUESTION_TYPE_TF):
            self._validate_tf_answers()
        else:
            raise quizgen.common.QuizValidationError(f"Unknown question type: '{self.question_type}'.")

    def _validate_tf_answers(self):
        if (not isinstance(self.answers, bool)):
            raise quizgen.common.QuizValidationError(f"'answers' for a T/F question must be a boolean, found '{self.answers}' ({type(self.answers)}).")

        # Change answers to look like multiple choice.
        self.answers = [
            {"correct": self.answers, "text": 'True'},
            {"correct": (not self.answers), "text": 'False'},
        ]

        self._validate_answer_list()

    def _validate_mdd_answers(self):
        if (len(self.answers) == 0):
            raise quizgen.common.QuizValidationError("No answers provided, at least one answer required.")

        self.answers_documents = {}

        for (key, answers) in self.answers.items():
            key_doc = quizgen.parser.parse_text(key, base_dir = self.base_dir)
            values_docs = _validate_answer_list(answers, self.base_dir, min_correct = 1, max_correct = 1)

            self.answers_documents[key] = {
                'key': key_doc,
                'values': values_docs,
            }

    def _validate_numerical_answers(self):
        _check_type(self.answers, list, "'answers' for a numerical question")

        for answer in self.answers:
            label = "values of 'answers' for a numerical question"
            _check_type(answer, dict, label)

            if ('type' not in answer):
                raise quizgen.common.QuizValidationError(f"Missing key ('type') for {label}.")

            if (answer['type'] == quizgen.constants.NUMERICAL_ANSWER_TYPE_EXACT):
                required_keys = ['value']

                if ('margin' not in answer):
                    answer['margin'] = 0
            elif (answer['type'] == quizgen.constants.NUMERICAL_ANSWER_TYPE_RANGE):
                required_keys = ['min', 'max']
            elif (answer['type'] == quizgen.constants.NUMERICAL_ANSWER_TYPE_PRECISION):
                required_keys = ['value', 'precision']
            else:
                raise quizgen.common.QuizValidationError(f"Unknown numerical answer type: '{answer['type']}'.")

            for key in required_keys:
                if (key not in answer):
                    raise quizgen.common.QuizValidationError(f"Missing required key '{key}' for numerical answer type '{answer['type']}'.")

    def _validate_fitb_answers(self):
        """
        "Short Answer" questions are actually fill in the blank questions.
        Just set up the answers to look like fill in multiple blanks with an empty key.
        """

        label = "short answer (fill in the blank)"

        _check_type(self.answers, list, f"{label} answers")

        if (len(self.answers) == 0):
            raise quizgen.common.QuizValidationError(f"Expected {label} answers to be non-empty.")

        self.answers = {"": self.answers}

        self._validate_fimb_answers(label = label)

    def _validate_fimb_answers(self, label = 'fill in multiple blanks'):
        if (not isinstance(self.answers, dict)):
            raise quizgen.common.QuizValidationError(f"Expected dict for {label} answers, found {type(self.answers)}.")

        if (len(self.answers) == 0):
            raise quizgen.common.QuizValidationError(f"Expected {label} answers to be non-empty.")

        for (key, values) in self.answers.items():
            if (not isinstance(values, list)):
                self.answers[key] = [values]

        for (key, values) in self.answers.items():
            _check_type(key, str, f"key for {label} answers")

            if (len(values) == 0):
                raise quizgen.common.QuizValidationError(f"Expected {label} possible values to be non-empty.")

            for value in values:
                _check_type(value, str, f"value for {label} answers")

        self.answers_documents = {}
        for (key, values) in self.answers.items():
            key_doc = quizgen.parser.parse_text(key, base_dir = self.base_dir)

            values_docs = []
            for value in values:
                values_docs.append(quizgen.parser.parse_text(value, base_dir = self.base_dir))

            self.answers_documents[key] = {
                'key': key_doc,
                'values': values_docs,
            }

    def _validate_matching_answers(self):
        if (not isinstance(self.answers, dict)):
            raise quizgen.common.QuizValidationError(f"Expected dict for matching answers, found {type(self.answers)}.")

        if ('matches' not in self.answers):
            raise quizgen.common.QuizValidationError("Matching answer type is missing the 'matches' field.")

        for match in self.answers['matches']:
            if (len(match) != 2):
                raise quizgen.common.QuizValidationError(f"Expected exactly two items for a match list, found {len(match)}.")

        if ('distractors' not in self.answers):
            self.answers['distractors'] = []

        for i in range(len(self.answers['distractors'])):
            distractor = self.answers['distractors'][i]
            if (not isinstance(distractor, str)):
                raise quizgen.common.QuizValidationError(f"Distractors must be strings, found {type(distractor)}.")

            distractor = distractor.strip()

            if ("\n" in distractor):
                raise quizgen.common.QuizValidationError(f"Distractors cannot have newlines, found {type(distractor)}.")

            self.answers['distractors'][i] = distractor

        self.answers_documents = {
            'matches': [],
            'distractors': [],
        }

        for (left, right) in self.answers['matches']:
            left_doc = quizgen.parser.parse_text(left, base_dir = self.base_dir)
            right_doc = quizgen.parser.parse_text(right, base_dir = self.base_dir)

            self.answers_documents['matches'].append([left_doc, right_doc])

        for distractor in self.answers['distractors']:
            doc = quizgen.parser.parse_text(distractor, base_dir = self.base_dir)
            self.answers_documents['distractors'].append(doc)

    def _validate_answer_list(self, min_correct = 0, max_correct = math.inf):
        self.answers_documents = _validate_answer_list(self.answers, self.base_dir,
                min_correct = min_correct, max_correct = max_correct)

    def to_dict(self, include_docs = True):
        value = self.__dict__.copy()

        value['answers'] = self._answers_to_dict(self.answers)

        if (include_docs):
            value['prompt_document'] = self.prompt_document.to_pod()
            value['answers_documents'] = self._answers_to_dict(self.answers_documents)
        else:
            del value['prompt_document']
            del value['answers_documents']

        return value

    def _answers_to_dict(self, target):
        if (isinstance(target, dict)):
            return {key: self._answers_to_dict(value) for (key, value) in target.items()}
        elif (isinstance(target, list)):
            return [self._answers_to_dict(answer) for answer in target]
        elif (isinstance(target, quizgen.parser.ParseNode)):
            return target.to_pod()
        else:
            return target

    def collect_file_paths(self):
        paths = []

        paths += self.prompt_document.collect_file_paths(self.base_dir)

        for document in self._collect_documents(self.answers):
            paths += document.collect_file_paths(self.base_dir)

        return paths

    def _collect_documents(self, target):
        if (isinstance(target, dict)):
            return self._collect_documents(list(target.values()))
        elif (isinstance(target, list)):
            documents = []
            for value in target:
                documents += self._collect_documents(value)
            return documents
        elif (isinstance(target, quizgen.parser.ParseNode)):
            return [target]
        else:
            return []

    @staticmethod
    def from_path(path):
        with open(path, 'r') as file:
            question_info = json5.load(file)

        # Check for a prompt file.
        prompt_path = os.path.join(os.path.dirname(path), PROMPT_FILENAME)
        if (os.path.exists(prompt_path)):
            question_info['prompt'] = quizgen.util.file.read(prompt_path)

        base_dir = os.path.dirname(path)

        return Question(base_dir = base_dir, **question_info)

    def copy(self):
        return copy.deepcopy(self)

def _check_type(value, expected_type, label):
    if (not isinstance(value, expected_type)):
        raise quizgen.common.QuizValidationError(f"{label} must be a {expected_type}, found '{value}' ({type(value)}).")

def _validate_answer_list(answers, base_dir, min_correct = 0, max_correct = math.inf):
    _check_type(answers, list, "'answers'")

    if (len(answers) == 0):
        raise quizgen.common.QuizValidationError(f"No answers provided, at least one answer required.")

    num_correct = 0
    for answer in answers:
        if ('correct' not in answer):
            raise quizgen.common.QuizValidationError(f"Answer has no 'correct' field (base_dir: '{base_dir}'.")

        if ('text' not in answer):
            raise quizgen.common.QuizValidationError(f"Answer has no 'text' field (base_dir: '{base_dir}'.")

        if (answer['correct']):
            num_correct += 1

    if (num_correct < min_correct):
        raise quizgen.common.QuizValidationError(f"Did not find enough correct answers. Expected at least {min_correct}, found {num_correct} (base_dir: '{base_dir}'.")

    if (num_correct > max_correct):
        raise quizgen.common.QuizValidationError(f"Found too many correct answers. Expected at most {max_correct}, found {num_correct} (base_dir: '{base_dir}'.")

    answers_documents = []
    for answer in answers:
        doc = quizgen.parser.parse_text(answer['text'], base_dir = base_dir)
        answers_documents.append(doc)

    return answers_documents
