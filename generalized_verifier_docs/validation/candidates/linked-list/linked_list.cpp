#include "linked_list.h"

namespace linked_list {

template <typename T>
List<T>::List() : head_(nullptr), tail_(nullptr), size_(0) {}

template <typename T>
void List<T>::push(T entry) {
    Node* newNode = new Node{entry, nullptr, nullptr};
    if (head_ == nullptr) {
        head_ = newNode;
        tail_ = newNode;
    } else {
        tail_->next = newNode;
        newNode->prev = tail_;
        tail_ = newNode;
    }
    ++size_;
}

template <typename T>
void List<T>::unshift(T entry) {
    Node* newNode = new Node{entry, nullptr, nullptr};
    if (head_ == nullptr) {
        head_ = newNode;
        tail_ = newNode;
    } else {
        head_->prev = newNode;
        newNode->next = head_;
        head_ = newNode;
    }
    ++size_;
}

template <typename T>
T List<T>::pop() {
    if (head_ == nullptr) {
        throw std::runtime_error("List is empty");
    }
    T data = head_->data;
    Node* temp = head_;
    head_ = head_->next;
    if (head_ == nullptr) {
        tail_ = nullptr;
    } else {
        head_->prev = nullptr;
    }
    delete temp;
    --size_;
    return data;
}

template <typename T>
T List<T>::shift() {
    if (head_ == nullptr) {
        throw std::runtime_error("List is empty");
    }
    T data = head_->data;
    Node* temp = head_;
    head_ = head_->next;
    if (head_ == nullptr) {
        tail_ = nullptr;
    } else {
        head_->prev = nullptr;
    }
    delete temp;
    --size_;
    return data;
}

template <typename T>
bool List<T>::erase(T entry) {
    if (head_ == nullptr) {
        return false;
    }
    Node* current = head_;
    while (current != nullptr) {
        if (current->data == entry) {
            if (current == head_ && current == tail_) {
                head_ = nullptr;
                tail_ = nullptr;
            } else if (current == head_) {
                head_ = head_->next;
                head_->prev = nullptr;
            } else if (current == tail_) {
                tail_ = tail_->prev;
                tail_->next = nullptr;
            } else {
                current->prev->next = current->next;
                current->next->prev = current->prev;
            }
            delete current;
            --size_;
            return true;
        }
        current = current->next;
    }
    return false;
}

template <typename T>
std::size_t List<T>::count() {
    return size_;
}

}  // namespace linked_list
