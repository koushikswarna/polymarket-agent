"""
Mock LLM clients for testing.

These mocks simulate Claude and GPT responses without making
real API calls. Essential for testing the probability engine.
"""

import json
from typing import Optional


class MockLLMClient:
    """
    Mock LLM client that returns predetermined responses.

    Use this in tests to:
    - Avoid API costs during testing
    - Control exactly what the "AI" returns
    - Test error handling
    - Speed up tests (no network calls)

    Example usage:
        mock = MockLLMClient()
        mock.set_response({
            "probability": 0.65,
            "confidence": 0.8,
            "reasoning": "Test reasoning"
        })

        # The mock will return this response
        response = mock.generate("Analyze this market")
    """

    def __init__(self):
        self._response: dict = {
            "probability": 0.50,
            "confidence": 0.50,
            "reasoning": "Mock response",
            "worth_deeper_analysis": True,
        }
        self._should_fail = False
        self._failure_message = "Mock API failure"
        self._call_count = 0

    def set_response(self, response: dict):
        """Set the response that will be returned."""
        self._response = response

    def set_should_fail(self, should_fail: bool, message: str = "Mock API failure"):
        """Make the client simulate failures."""
        self._should_fail = should_fail
        self._failure_message = message

    def get_call_count(self) -> int:
        """Get how many times the client was called."""
        return self._call_count

    def reset_call_count(self):
        """Reset the call counter."""
        self._call_count = 0

    def generate(self, prompt: str) -> str:
        """Simulate generating a response."""
        self._call_count += 1

        if self._should_fail:
            raise Exception(self._failure_message)

        return json.dumps(self._response)


class MockAnthropicClient:
    """
    Mock Anthropic (Claude) client.

    Simulates the Anthropic Python SDK's interface.
    """

    def __init__(self):
        self._response = {
            "probability": 0.65,
            "confidence": 0.75,
            "base_rate": 0.50,
            "reasoning": "Mock Claude analysis",
            "trade_recommendation": "BUY_YES",
        }
        self._should_fail = False
        self._call_count = 0

    @property
    def messages(self):
        """Return self to simulate the messages interface."""
        return self

    def create(self, **kwargs):
        """Simulate creating a message."""
        self._call_count += 1

        if self._should_fail:
            raise Exception("Mock Anthropic API failure")

        # Return a mock response object
        class MockContent:
            def __init__(self, text):
                self.text = text

        class MockResponse:
            def __init__(self, response_dict):
                self.content = [MockContent(json.dumps(response_dict))]

        return MockResponse(self._response)

    def set_response(self, response: dict):
        """Set the response to return."""
        self._response = response

    def set_should_fail(self, should_fail: bool):
        """Make the client fail."""
        self._should_fail = should_fail


class MockOpenAIClient:
    """
    Mock OpenAI client.

    Simulates the OpenAI Python SDK's interface.
    """

    def __init__(self):
        self._response = {
            "probability": 0.55,
            "confidence": 0.6,
            "reasoning": "Mock GPT screening",
            "worth_deeper_analysis": True,
        }
        self._should_fail = False
        self._call_count = 0

    @property
    def chat(self):
        """Return self to simulate the chat interface."""
        return self

    @property
    def completions(self):
        """Return self to simulate the completions interface."""
        return self

    def create(self, **kwargs):
        """Simulate creating a completion."""
        self._call_count += 1

        if self._should_fail:
            raise Exception("Mock OpenAI API failure")

        # Return a mock response object
        class MockMessage:
            def __init__(self, content):
                self.content = content

        class MockChoice:
            def __init__(self, response_dict):
                self.message = MockMessage(json.dumps(response_dict))

        class MockResponse:
            def __init__(self, response_dict):
                self.choices = [MockChoice(response_dict)]

        return MockResponse(self._response)

    def set_response(self, response: dict):
        """Set the response to return."""
        self._response = response

    def set_should_fail(self, should_fail: bool):
        """Make the client fail."""
        self._should_fail = should_fail
