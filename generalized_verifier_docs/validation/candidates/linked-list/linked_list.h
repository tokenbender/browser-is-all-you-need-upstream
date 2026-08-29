#pragma once

#include <cstddef>
#include <stdexcept>

namespace linked_list {

template <typename T>
class List {
public:
    List();
    void push(T entry);
    void unshift(T entry);
    T pop();
    T shift();
    bool erase(T entry);
    std::size_t count();

private:
    struct Node {
        T data;
        Node* next;
        Node* prev;
    };

    Node* head_;
    Node* tail_;
    std::size_t size_;
};

}  // namespace linked_list
